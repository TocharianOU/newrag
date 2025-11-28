import React from 'react';
import { Server, Copy, Terminal, BookOpen } from 'lucide-react';

export default function McpPage() {
  const mcpUrl = import.meta.env.VITE_MCP_URL || 'http://localhost:3001/mcp';
  const mcpHost = import.meta.env.VITE_MCP_HOST_DISPLAY || 'localhost';
  const mcpPort = import.meta.env.VITE_MCP_PORT || '3001';

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    // You might want to add a toast notification here
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold text-slate-900 dark:text-white flex items-center gap-3">
          <Server className="w-8 h-8 text-indigo-600 dark:text-indigo-400" />
          MCP 服务信息
        </h1>
        <p className="text-slate-600 dark:text-slate-400 text-lg">
          Model Context Protocol (MCP) 服务端点配置与说明
        </p>
      </div>

      {/* Connection Info Card */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Terminal className="w-5 h-5 text-slate-500" />
            连接信息
          </h2>
        </div>
        <div className="p-6 space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-500 dark:text-slate-400">
                MCP Streamable HTTP 端点 URL
              </label>
              <div className="flex items-center gap-2">
                <code className="flex-1 p-3 bg-slate-100 dark:bg-slate-800 rounded-lg text-slate-900 dark:text-slate-100 font-mono text-sm border border-slate-200 dark:border-slate-700">
                  {mcpUrl}
                </code>
                <button
                  onClick={() => copyToClipboard(mcpUrl)}
                  className="p-2.5 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg text-slate-500 hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-400 transition-colors border border-transparent hover:border-slate-200 dark:hover:border-slate-700"
                  title="复制 URL"
                >
                  <Copy size={18} />
                </button>
              </div>
              <p className="text-xs text-slate-500">
                在 NewChat、Cursor 或其他 MCP 客户端中使用此 URL 进行连接。
              </p>
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-500 dark:text-slate-400">
                服务状态
              </label>
              <div className="flex items-center gap-3 p-3 bg-green-50 dark:bg-green-900/20 border border-green-100 dark:border-green-900/30 rounded-lg">
                <div className="relative flex h-3 w-3">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
                </div>
                <span className="text-green-700 dark:text-green-400 font-medium text-sm">
                  运行中 (Port {mcpPort})
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Capabilities Card */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="p-6 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-slate-500" />
            功能说明
          </h2>
        </div>
        <div className="p-6">
          <div className="prose dark:prose-invert max-w-none text-slate-600 dark:text-slate-400">
            <p className="mb-4">
              NewRAG MCP 服务器提供了一套标准化的接口，允许 AI 助手直接与您的知识库进行交互。
              通过集成此 MCP 服务，您可以：
            </p>
            <ul className="grid gap-3 md:grid-cols-2 list-none pl-0">
              <li className="flex gap-3 items-start">
                <div className="mt-1 w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                <span>
                  <strong className="text-slate-900 dark:text-slate-200">混合检索：</strong> 
                  结合向量语义搜索和 BM25 关键词搜索，精准定位文档内容。
                </span>
              </li>
              <li className="flex gap-3 items-start">
                <div className="mt-1 w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                <span>
                  <strong className="text-slate-900 dark:text-slate-200">元数据查询：</strong> 
                  访问文档的完整元数据，包括文件名、作者、上传时间等。
                </span>
              </li>
              <li className="flex gap-3 items-start">
                <div className="mt-1 w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                <span>
                  <strong className="text-slate-900 dark:text-slate-200">直接 API 访问：</strong> 
                  提供执行原始 Elasticsearch 查询的能力，用于复杂分析。
                </span>
              </li>
              <li className="flex gap-3 items-start">
                <div className="mt-1 w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                <span>
                  <strong className="text-slate-900 dark:text-slate-200">上下文集成：</strong> 
                  让 AI 助手能够"阅读"您的本地文档库，回答相关问题。
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

