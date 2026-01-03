import apiClient from './client';

export interface McpToken {
  id: number;
  name: string;
  token: string;
  created_at: string;
  expires_at: string | null;
  last_used: string | null;
  is_active: boolean;
}

export interface CreateMcpTokenRequest {
  name: string;
  expires_days?: number;
}

/**
 * Get all MCP tokens for the current user
 */
export async function listMcpTokens(): Promise<McpToken[]> {
  const response = await apiClient.get('/auth/mcp-tokens');
  return response.data;
}

/**
 * Create a new MCP token
 */
export async function createMcpToken(data: CreateMcpTokenRequest): Promise<McpToken> {
  const response = await apiClient.post('/auth/mcp-tokens', data);
  return response.data;
}

/**
 * Delete an MCP token
 */
export async function deleteMcpToken(tokenId: number): Promise<void> {
  await apiClient.delete(`/auth/mcp-tokens/${tokenId}`);
}

