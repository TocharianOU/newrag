import apiClient from './client';

export interface Stats {
  total_documents: number;
  total_chunks: number;
  total_size_mb: number;
  documents_by_type: Record<string, number>;
  documents_by_status: Record<string, number>;
  recent_uploads: Array<{
    filename: string;
    created_at: string;
    status: string;
  }>;
}

export const statsAPI = {
  // 获取统计信息
  get: async () => {
    const response = await apiClient.get<Stats>('/stats');
    return response.data;
  },

  // 健康检查
  health: async () => {
    const response = await apiClient.get('/health');
    return response.data;
  },
};


