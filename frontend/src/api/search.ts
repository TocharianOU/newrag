import apiClient from './client';

export interface SearchRequest {
  query: string;
  k?: number;
  filters?: Record<string, any>;
  use_hybrid?: boolean;
}

export interface PageData {
  page_num: number;
  image_path: string;
  visualized_path: string;
  ocr_json_path: string;
  text_count: number;
  components: string[];
}

export interface MatchedBBox {
  text: string;
  confidence: number;
  bbox: [number, number, number, number]; // [x1, y1, x2, y2]
}

export interface SearchResult {
  id: string;
  text: string;
  content?: string;     // Some backends return 'content'
  highlighted?: string; // Search highlighting
  score: number;
  matched_bboxes?: MatchedBBox[];
  metadata: {
    document_id?: string;
    filename?: string;
    filepath?: string;
    file_type?: string;
    page_number?: number;
    page?: number; // Alternative to page_number
    category?: string;
    author?: string;
    tags?: string[];
    extraction_method?: string;
    ocr_engine?: string;
    pages_data?: PageData[];
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
