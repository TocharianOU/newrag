#!/usr/bin/env node

/*
 * NewRAG Search MCP Server
 * 专为 NewRAG 项目设计的Elasticsearch搜索服务
 */

import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { Client, estypes, ClientOptions } from "@elastic/elasticsearch";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express, { Request, Response, NextFunction } from "express";
import { randomUUID } from "crypto";
import fs from "fs";
import yaml from "js-yaml";
import path from "path";
import { fileURLToPath } from "url";
import jwt from "jsonwebtoken";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// JWT Configuration (should match backend config)
const JWT_SECRET = process.env.JWT_SECRET || "your-super-secret-key-please-change-this-in-production";
const JWT_ALGORITHM = "HS256";

// User context extracted from JWT
interface UserContext {
  id: number;
  username: string;
  org_id: number | null;
  is_superuser: boolean;
  roles: string[];
}

// Extend Express Request to include user
declare global {
  namespace Express {
    interface Request {
      user?: UserContext;
    }
  }
}

// Configuration schema with auth options
const ConfigSchema = z
  .object({
    url: z
      .string()
      .trim()
      .min(1, "Elasticsearch URL cannot be empty")
      .url("Invalid Elasticsearch URL format")
      .describe("Elasticsearch server URL"),

    apiKey: z
      .string()
      .optional()
      .describe("API key for Elasticsearch authentication"),

    username: z
      .string()
      .optional()
      .describe("Username for Elasticsearch authentication"),

    password: z
      .string()
      .optional()
      .describe("Password for Elasticsearch authentication"),

    caCert: z
      .string()
      .optional()
      .describe("Path to custom CA certificate for Elasticsearch"),
  })
  .refine(
    (data) => {
      if (data.username) {
        return !!data.password;
      }
      if (data.password) {
        return !!data.username;
      }
      if (data.apiKey) {
        return true;
      }
      return true;
    },
    {
      message:
        "Either ES_API_KEY or both ES_USERNAME and ES_PASSWORD must be provided, or no auth for local development",
      path: ["username", "password"],
    }
  );

type ElasticsearchConfig = z.infer<typeof ConfigSchema>;

// RAG配置类型
interface RagConfig {
  models: {
    embedding: {
      provider: string;
      api_url: string;
      api_key: string;
      model_name: string;
      dimensions: number;
      batch_size: number;
      timeout: number;
    };
  };
  elasticsearch: {
    hosts: string[];
    index_name: string;
    username: string;
    password: string;
    timeout: number;
    max_retries: number;
    retry_on_timeout: boolean;
    hybrid_search: {
      enabled: boolean;
      vector_weight: number;
      bm25_weight: number;
    };
  };
  mcp?: {
    host?: string;
    port?: number;
  };
}

// 从config.yaml加载RAG配置
function loadRagConfig(): RagConfig | null {
  try {
    // 尝试从多个可能的路径加载配置
    const possiblePaths = [
      path.join(__dirname, "../config.yaml"),
      path.join(process.cwd(), "config.yaml"),
      path.join(__dirname, "../../config.yaml"),
    ];

    for (const configPath of possiblePaths) {
      if (fs.existsSync(configPath)) {
        const fileContents = fs.readFileSync(configPath, "utf8");
        const config = yaml.load(fileContents) as RagConfig;
        process.stderr.write(`✓ Loaded RAG config from: ${configPath}\n`);
        return config;
      }
    }

    process.stderr.write("⚠ Warning: config.yaml not found, using default settings\n");
    return null;
  } catch (error) {
    process.stderr.write(
      `Error loading config.yaml: ${
        error instanceof Error ? error.message : String(error)
      }\n`
    );
    return null;
  }
}

// JWT验证中间件
function jwtAuthMiddleware(req: Request, res: Response, next: NextFunction) {
  // 从 Authorization header 提取 token
  const authHeader = req.headers.authorization;
  
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return res.status(401).json({
      jsonrpc: "2.0",
      error: {
        code: -32001,
        message: "Authentication required. Please provide a valid JWT token.",
      },
      id: null,
    });
  }

  const token = authHeader.substring(7); // 移除 "Bearer "

  try {
    // 验证 JWT
    const decoded = jwt.verify(token, JWT_SECRET, {
      algorithms: [JWT_ALGORITHM as jwt.Algorithm],
    }) as any;

    // 提取用户信息
    req.user = {
      id: parseInt(decoded.sub),
      username: decoded.username,
      org_id: decoded.org_id || null,
      is_superuser: decoded.is_superuser || false,
      roles: decoded.roles || [],
    };

    next();
  } catch (error) {
    return res.status(401).json({
      jsonrpc: "2.0",
      error: {
        code: -32001,
        message: `Invalid or expired token: ${error instanceof Error ? error.message : String(error)}`,
      },
      id: null,
    });
  }
}

// 构建权限过滤查询
function buildPermissionFilter(user?: UserContext): any {
  if (!user) {
    // 无用户上下文，只返回公开文档
    return {
      term: { "metadata.visibility": "public" },
    };
  }

  // Superuser 可以看所有文档
  if (user.is_superuser) {
    return { match_all: {} };
  }

  const permissionFilters: any[] = [
    // 用户拥有的文档
    { term: { "metadata.owner_id": user.id } },
    // 公开文档
    { term: { "metadata.visibility": "public" } },
  ];

  // 分享给该用户的文档
  permissionFilters.push({
    term: { "metadata.shared_with_users": user.id },
  });

  // 组织级别的文档
  if (user.org_id) {
    permissionFilters.push({
      bool: {
        must: [
          { term: { "metadata.org_id": user.org_id } },
          { term: { "metadata.visibility": "org" } },
        ],
      },
    });
  }

  // 根据角色共享的文档
  if (user.roles && user.roles.length > 0) {
    for (const role of user.roles) {
      permissionFilters.push({
        term: { "metadata.shared_with_roles": role },
      });
    }
  }

  return {
    bool: {
      should: permissionFilters,
      minimum_should_match: 1,
    },
  };
}

// 调用embedding API生成向量
async function generateEmbedding(
  text: string,
  ragConfig: RagConfig | null
): Promise<number[]> {
  if (!ragConfig) {
    throw new Error("RAG configuration not loaded, cannot generate embeddings");
  }

  const { api_url, api_key, model_name, timeout } = ragConfig.models.embedding;

  try {
    const response = await fetch(`${api_url}/embeddings`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${api_key}`,
      },
      body: JSON.stringify({
        model: model_name,
        input: text,
      }),
      signal: AbortSignal.timeout(timeout * 1000),
    });

    if (!response.ok) {
      throw new Error(`Embedding API failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.data[0].embedding;
  } catch (error) {
    throw new Error(
      `Failed to generate embedding: ${
        error instanceof Error ? error.message : String(error)
      }`
    );
  }
}

export async function createElasticsearchMcpServer(
  config: ElasticsearchConfig,
  ragConfig: RagConfig | null,
  user?: UserContext
) {
  const validatedConfig = ConfigSchema.parse(config);
  const { url, apiKey, username, password, caCert } = validatedConfig;

  const clientOptions: ClientOptions = {
    node: url,
    maxRetries: 5,
    requestTimeout: 60000,
    compression: true,
  };

  if (apiKey) {
    clientOptions.auth = { apiKey };
  } else if (username && password) {
    clientOptions.auth = { username, password };
  }

  if (caCert) {
    try {
      const ca = fs.readFileSync(caCert);
      clientOptions.tls = { ca };
    } catch (error) {
      console.error(
        `Failed to read certificate file: ${
          error instanceof Error ? error.message : String(error)
        }`
      );
    }
  }

  const esClient = new Client(clientOptions);

  const server = new McpServer({
    name: "newrag-search",
    version: "1.0.0",
  });

  // 工具1: 智能混合搜索 (向量 + BM25)
  // 该工具会自动将用户的查询文本转换为向量，并执行混合搜索
  // 大模型只需提供搜索关键词，无需关心embedding细节
  server.tool(
    "hybrid_search",
    `执行智能混合搜索（向量搜索 + 关键词搜索）。
    
该工具会自动处理以下步骤：
1. 自动将查询文本转换为向量表示（使用配置的embedding模型）
2. 同时执行语义向量搜索和BM25关键词搜索
3. 按配置的权重合并结果（默认: 向量70% + BM25 30%）
4. 返回最相关的文档片段

使用场景：
- 查找与问题语义相关的文档
- 智能问答和知识检索
- 模糊查询和概念搜索

注意：只需提供查询文本，系统会自动完成向量化和混合搜索。`,
    {
      query: z
        .string()
        .trim()
        .min(1, "Query text is required")
        .describe("搜索查询文本，可以是问题、关键词或描述"),

      index: z
        .string()
        .optional()
        .describe("可选：指定索引名称，默认使用配置文件中的索引"),

      size: z
        .number()
        .int()
        .positive()
        .max(100)
        .optional()
        .default(10)
        .describe("返回结果数量，默认10条"),

      min_score: z
        .number()
        .min(0)
        .max(1)
        .optional()
        .describe("可选：最低相关度分数阈值(0-1)，过滤低相关度结果"),
    },
    async ({ query, index, size = 10, min_score }) => {
      try {
        // 使用配置文件中的索引名称
        const targetIndex =
          index || ragConfig?.elasticsearch?.index_name || "aiops_knowledge_base";

        // 自动生成查询向量
        process.stderr.write(`🔄 Generating embedding for query: "${query}"\n`);
        const queryVector = await generateEmbedding(query, ragConfig);
        process.stderr.write(`✓ Embedding generated (${queryVector.length} dimensions)\n`);

        // 获取混合搜索权重配置
        const vectorWeight =
          ragConfig?.elasticsearch?.hybrid_search?.vector_weight || 0.7;
        const bm25Weight =
          ragConfig?.elasticsearch?.hybrid_search?.bm25_weight || 0.3;

        // 构建权限过滤
        const permissionFilter = buildPermissionFilter(user);

        // 构建混合搜索查询（与web项目保持一致）
        const searchBody: any = {
          size,
          query: {
            bool: {
              must: [
                // 权限过滤
                permissionFilter,
              ],
              should: [
                // 向量搜索部分
                {
                  script_score: {
                    query: { match_all: {} },
                    script: {
                      source: `cosineSimilarity(params.query_vector, 'content_vector') * ${vectorWeight}`,
                      params: {
                        query_vector: queryVector,
                      },
                    },
                  },
                },
                // BM25关键词搜索部分
                {
                  multi_match: {
                    query: query,
                    fields: [
                      "text^3",                    // 主要内容（最高优先级）
                      "metadata.filename^2.5",     // 文件名
                      "metadata.description^2",    // 描述
                      "metadata.filepath^1.5",     // 文件路径
                      "document_name^2",           // 文档名称
                      "drawing_number^2",          // 图纸编号
                      "project_name^1.5",          // 项目名称
                      "equipment_tags^1.2",        // 设备标签
                      "component_details"          // 元件详情
                    ],
                    type: "best_fields",
                    boost: bm25Weight,
                    operator: "or",
                    fuzziness: "AUTO",
                  },
                },
              ],
            },
          },
          // 高亮显示匹配内容
          highlight: {
            fields: {
              text: {
                fragment_size: 150,
                number_of_fragments: 3,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
              "metadata.filename": {
                fragment_size: 200,
                number_of_fragments: 1,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
              "metadata.description": {
                fragment_size: 150,
                number_of_fragments: 1,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
              "metadata.filepath": {
                fragment_size: 200,
                number_of_fragments: 1,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
              document_name: {
                fragment_size: 150,
                number_of_fragments: 1,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
              drawing_number: {
                fragment_size: 100,
                number_of_fragments: 1,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
              project_name: {
                fragment_size: 150,
                number_of_fragments: 1,
                pre_tags: ["<mark>"],
                post_tags: ["</mark>"],
              },
            },
            require_field_match: false,
          },
          // 不限制返回字段，返回完整的_source
          // _source: true  // 默认就是true，返回所有字段
        };

        // 添加最低分数过滤
        if (min_score !== undefined) {
          searchBody.min_score = min_score;
        }

        // 执行搜索
        const result = await esClient.search({
          index: targetIndex,
          body: searchBody,
        });

        const totalHits =
          typeof result.hits.total === "number"
            ? result.hits.total
            : result.hits.total?.value || 0;

        // 格式化结果
        const formattedResults = result.hits.hits.map((hit: any, idx: number) => {
          const source = hit._source || {};
          const highlights = hit.highlight || {};
          const metadata = source.metadata || {};

          let resultText = `\n━━━ 结果 ${idx + 1} (相关度: ${hit._score?.toFixed(3)}) ━━━\n`;

          // ES文档ID (重要)
          resultText += `🔑 ES文档ID: ${hit._id}\n`;

          // 文档基本信息
          if (metadata.filename) {
            resultText += `📄 文件名: ${
              highlights["metadata.filename"]
                ? highlights["metadata.filename"][0]
                : metadata.filename
            }\n`;
          }
          if (metadata.filepath) {
            resultText += `📁 文件路径: ${metadata.filepath}\n`;
          }
          if (metadata.page_number) {
            resultText += `📃 页码: ${metadata.page_number}`;
            if (metadata.total_pages) {
              resultText += ` / ${metadata.total_pages}`;
            }
            resultText += `\n`;
          }

          // 文档标识信息
          if (metadata.checksum) {
            resultText += `#️⃣  Checksum: ${metadata.checksum.substring(0, 16)}...\n`;
          }
          if (metadata.document_id) {
            resultText += `🆔 文档ID: ${metadata.document_id}\n`;
          }

          // 文档名称和图纸编号
          if (source.document_name) {
            resultText += `🏷️  文档名称: ${
              highlights.document_name
                ? highlights.document_name[0]
                : source.document_name
            }\n`;
          }
          if (source.drawing_number) {
            resultText += `🔢 图纸编号: ${
              highlights.drawing_number
                ? highlights.drawing_number[0]
                : source.drawing_number
            }\n`;
          }
          if (source.project_name) {
            resultText += `🏗️  项目名称: ${
              highlights.project_name
                ? highlights.project_name[0]
                : source.project_name
            }\n`;
          }

          // 原始文件URL (重要!)
          if (metadata.original_file_url) {
            resultText += `\n📥 原始文件:\n`;
            resultText += `   URL: ${metadata.original_file_url}\n`;
            resultText += `   (可直接下载PDF/DOCX等原始文档)\n`;
          }

          // MinIO图片资源
          if (metadata.page_image_url) {
            resultText += `\n📷 页面图片:\n`;
            resultText += `   URL: ${metadata.page_image_url}\n`;
          }
          
          // MinIO存储信息
          if (metadata.minio_bucket || metadata.minio_prefix) {
            resultText += `\n💾 MinIO存储:\n`;
            if (metadata.minio_bucket) {
              resultText += `   Bucket: ${metadata.minio_bucket}\n`;
            }
            if (metadata.minio_prefix) {
              resultText += `   Prefix: ${metadata.minio_prefix}\n`;
            }
            if (metadata.minio_base_url) {
              resultText += `   Base URL: ${metadata.minio_base_url}\n`;
            }
          }

          // 元数据补充
          if (metadata.chunk_id) {
            resultText += `\n🧩 分块信息:\n`;
            resultText += `   Chunk ID: ${metadata.chunk_id}\n`;
            if (metadata.chunk_index !== undefined && metadata.total_chunks !== undefined) {
              resultText += `   分块位置: ${metadata.chunk_index + 1} / ${metadata.total_chunks}\n`;
            }
          }

          // 匹配内容
          resultText += `\n📝 匹配内容:\n`;
          if (highlights.text && highlights.text.length > 0) {
            resultText += highlights.text.join("\n...\n") + "\n";
          } else if (source.text) {
            const preview =
              source.text.length > 300
                ? source.text.substring(0, 300) + "..."
                : source.text;
            resultText += preview + "\n";
          }

          // 返回结构化JSON (方便程序化处理)
          resultText += `\n📋 结构化数据:\n`;
          resultText += JSON.stringify({
            es_id: hit._id,
            score: hit._score,
            document_id: metadata.document_id,
            checksum: metadata.checksum,
            filename: metadata.filename,
            page_number: metadata.page_number,
            total_pages: metadata.total_pages,
            original_file_url: metadata.original_file_url,  // 原始PDF/DOCX等
            page_image_url: metadata.page_image_url,        // 页面PNG图片
            minio_bucket: metadata.minio_bucket,
            minio_prefix: metadata.minio_prefix,
            minio_base_url: metadata.minio_base_url,
            chunk_id: metadata.chunk_id,
            drawing_number: source.drawing_number,
            project_name: source.project_name,
          }, null, 2) + "\n";

          return resultText;
        });

        const summary = `
🔍 混合搜索完成
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
查询: "${query}"
索引: ${targetIndex}
总结果数: ${totalHits}
返回数量: ${result.hits.hits.length}
搜索策略: 向量搜索(${(vectorWeight * 100).toFixed(0)}%) + BM25关键词(${(
          bm25Weight * 100
        ).toFixed(0)}%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`;

        return {
          content: [
            {
              type: "text" as const,
              text: summary + formattedResults.join("\n"),
            },
          ],
        };
      } catch (error) {
        console.error(
          `Hybrid search failed: ${
            error instanceof Error ? error.message : String(error)
          }`
        );
        return {
          content: [
            {
              type: "text" as const,
              text: `❌ 搜索失败: ${
                error instanceof Error ? error.message : String(error)
              }`,
            },
          ],
        };
      }
    }
  );

  // 工具2: 直接执行Elasticsearch API
  // 提供完整的ES API访问能力，用于高级查询、聚合分析、索引管理等
  server.tool(
    "execute_es_api",
    `直接执行任意Elasticsearch API端点。
    
该工具提供对Elasticsearch的完全访问权限，可用于：
- 执行自定义查询DSL（不使用向量的纯BM25搜索、布尔查询等）
- 聚合分析（统计、分组、趋势分析）
- 索引管理（查看mapping、settings、创建/删除索引）
- 集群管理（健康检查、节点信息、分片状态）

使用场景：
- 需要精确控制查询逻辑时
- 执行聚合统计分析
- 查看索引结构和mappings
- 执行不需要向量搜索的场景

示例端点：
- _search: 搜索
- _mapping: 查看字段映射
- _settings: 查看索引设置
- _cat/indices: 列出所有索引
- _cluster/health: 集群健康状态`,
    {
      method: z
        .enum(["GET", "POST", "PUT", "DELETE", "HEAD"])
        .describe("HTTP请求方法"),

      path: z
        .string()
        .trim()
        .min(1)
        .describe(
          "API端点路径 (例如: '_search', 'my_index/_search', '_cluster/health')"
        ),

      params: z
        .record(z.any())
        .optional()
        .describe("可选：URL查询参数"),

      body: z
        .record(z.any())
        .optional()
        .describe("可选：请求体（JSON对象）"),

      headers: z
        .record(z.string())
        .optional()
        .describe("可选：自定义HTTP头"),
    },
    async ({ method, path, params, body, headers }) => {
      try {
        const sanitizedPath = path.startsWith("/") ? path.substring(1) : path;

        let customHeaders = headers || {};
        if (body && !customHeaders["Content-Type"]) {
          customHeaders["Content-Type"] = "application/json";
        }

        const options: any = {
          method,
          path: sanitizedPath,
          querystring: params || {},
          body: body || undefined,
          headers: customHeaders,
        };

        const response = await esClient.transport.request(options);

        return {
          content: [
            {
              type: "text" as const,
              text: `✓ 成功执行 ${method} ${path}`,
            },
            {
              type: "text" as const,
              text: JSON.stringify(response, null, 2),
            },
          ],
        };
      } catch (error) {
        console.error(
          `Elasticsearch API request failed: ${
            error instanceof Error ? error.message : String(error)
          }`
        );

        let errorDetails = "";
        if (error instanceof Error && "meta" in error && error.meta) {
          const meta = error.meta as any;
          if (meta.body) {
            errorDetails = `\n错误详情: ${JSON.stringify(meta.body, null, 2)}`;
          }
        }

        return {
          content: [
            {
              type: "text" as const,
              text: `❌ API调用失败: ${
                error instanceof Error ? error.message : String(error)
              }${errorDetails}`,
            },
          ],
        };
      }
    }
  );

  return server;
}

// 加载配置
const ragConfig = loadRagConfig();

const config: ElasticsearchConfig = {
  url: ragConfig?.elasticsearch?.hosts[0] || process.env.ES_URL || "http://localhost:9200",
  apiKey: ragConfig?.elasticsearch?.password ? undefined : (process.env.ES_API_KEY || ""), // 优先用 user/pass
  username: ragConfig?.elasticsearch?.username || process.env.ES_USERNAME || "",
  password: ragConfig?.elasticsearch?.password || process.env.ES_PASSWORD || "",
  caCert: process.env.ES_CA_CERT || "",
};

async function main() {
  try {
    const useHttp = process.env.MCP_TRANSPORT === "http";
    
    // 优先使用环境变量，其次使用配置文件，最后使用默认值
    let httpPort = parseInt(process.env.MCP_HTTP_PORT || "0");
    let httpHost = process.env.MCP_HTTP_HOST || "";

    if (httpPort === 0 && ragConfig?.mcp?.port) {
      httpPort = ragConfig.mcp.port;
    }
    if (httpPort === 0) {
      httpPort = 3000;
    }

    if (!httpHost && ragConfig?.mcp?.host) {
      httpHost = ragConfig.mcp.host;
    }
    if (!httpHost) {
      httpHost = "localhost";
    }

    if (useHttp) {
      // HTTP模式
      process.stderr.write(
        `🚀 Starting NewRAG Search MCP Server (HTTP mode) on ${httpHost}:${httpPort}\n`
      );

      const app = express();
      app.use(express.json());

      const transports = new Map<string, StreamableHTTPServerTransport>();

      app.get("/health", (req, res) => {
        res.json({
          status: "ok",
          service: "newrag-search",
          transport: "streamable-http",
          elasticsearch_url: config.url,
          rag_config_loaded: ragConfig !== null,
        });
      });

      app.post("/mcp", jwtAuthMiddleware, async (req, res) => {
        const sessionId = req.headers["mcp-session-id"] as string | undefined;

        try {
          let transport: StreamableHTTPServerTransport;

          if (sessionId && transports.has(sessionId)) {
            transport = transports.get(sessionId)!;
          } else {
            transport = new StreamableHTTPServerTransport({
              sessionIdGenerator: () => randomUUID(),
              onsessioninitialized: async (newSessionId: string) => {
                transports.set(newSessionId, transport);
                process.stderr.write(`✓ New MCP session: ${newSessionId} (User: ${req.user?.username})\n`);
              },
              onsessionclosed: async (closedSessionId: string) => {
                transports.delete(closedSessionId);
                process.stderr.write(`✓ Session closed: ${closedSessionId}\n`);
              },
            });

            // 创建 MCP server 时传入用户上下文
            const server = await createElasticsearchMcpServer(config, ragConfig, req.user);
            await server.connect(transport);
          }

          await transport.handleRequest(req, res, req.body);
        } catch (error) {
          process.stderr.write(`❌ Error handling MCP request: ${error}\n`);
          if (!res.headersSent) {
            res.status(500).json({
              jsonrpc: "2.0",
              error: {
                code: -32603,
                message: "Internal server error",
              },
              id: null,
            });
          }
        }
      });

      app.get("/mcp", jwtAuthMiddleware, async (req, res) => {
        const sessionId = req.headers["mcp-session-id"] as string | undefined;

        if (!sessionId || !transports.has(sessionId)) {
          res.status(400).json({
            jsonrpc: "2.0",
            error: {
              code: -32000,
              message: "Invalid or missing session ID",
            },
            id: null,
          });
          return;
        }

        try {
          const transport = transports.get(sessionId)!;
          await transport.handleRequest(req, res);
        } catch (error) {
          process.stderr.write(`❌ Error handling SSE stream: ${error}\n`);
          if (!res.headersSent) {
            res.status(500).json({
              jsonrpc: "2.0",
              error: {
                code: -32603,
                message: "Failed to establish SSE stream",
              },
              id: null,
            });
          }
        }
      });

      app.listen(httpPort, httpHost, () => {
        console.log(`\n✓ NewRAG Search MCP Server is running`);
        console.log(`  Endpoint: http://${httpHost}:${httpPort}/mcp`);
        console.log(`  Health: http://${httpHost}:${httpPort}/health`);
        console.log(`  Elasticsearch: ${config.url}`);
        console.log(`  RAG Config: ${ragConfig ? "✓ Loaded" : "⚠ Not found"}\n`);
      });

      process.on("SIGINT", async () => {
        console.log("\n⏹ Shutting down server...");
        for (const [sessionId, transport] of transports.entries()) {
          await transport.close();
        }
        process.exit(0);
      });
    } else {
      // Stdio模式 (默认) - 本地调试模式，无需JWT认证
      process.stderr.write(`🚀 Starting NewRAG Search MCP Server (Stdio mode)\n`);
      process.stderr.write(`⚠ Note: Stdio mode bypasses JWT authentication\n`);

      const transport = new StdioServerTransport();
      // Stdio 模式不传入用户上下文，将显示所有公开文档
      const server = await createElasticsearchMcpServer(config, ragConfig, undefined);

      await server.connect(transport);

      process.on("SIGINT", async () => {
        await server.close();
        process.exit(0);
      });
    }
  } catch (error) {
    console.error("❌ Fatal error:", error);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(
    "❌ Server error:",
    error instanceof Error ? error.message : String(error)
  );
  process.exit(1);
});
