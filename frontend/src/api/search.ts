import apiClient from './client';

export interface SearchRequest {
  query: string;
  k?: number;
  filters?: Record<string, any>;
  use_hybrid?: boolean;
}

export interface SearchResult {
  id: string;
  text: string;
  score: number;
  metadata: {
    document_id?: string;
    filename?: string;
    page_number?: number;
    category?: string;
    tags?: string[];
    [key: string]: any;
  };
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

export const searchAPI = {
  // 搜索文档
  search: async (request: SearchRequest) => {
    const response = await apiClient.post<SearchResponse>('/search', request);
    return response.data;
  },

  // 获取组件详情
  getComponent: async (componentId: string, k: number = 10) => {
    const response = await apiClient.get(`/component/${componentId}`, {
      params: { k }
    });
    return response.data;
  },
};

