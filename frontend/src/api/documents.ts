import apiClient from './client';

export interface Document {
  id: number;
  filename: string;
  file_path: string;
  file_type: string;
  file_size: number;
  checksum: string;
  status: string;
  total_pages?: number;
  processed_pages?: number;
  progress_percentage?: number;
  progress_message?: string;
  created_at: string;
  updated_at: string;
  category?: string;
  tags?: string[];
}

export interface DocumentListResponse {
  documents: Document[];
  total: number;
}

export const documentAPI = {
  // 获取文档列表
  list: async (params?: { limit?: number; offset?: number; status?: string }) => {
    const response = await apiClient.get<DocumentListResponse>('/documents', { params });
    return response.data;
  },

  // 获取文档进度
  getProgress: async (docId: number, includeChildren: boolean = false) => {
    const response = await apiClient.get(`/documents/${docId}/progress`, {
      params: { include_children: includeChildren }
    });
    return response.data;
  },

  // 上传文件
  upload: async (file: File, metadata?: {
    category?: string;
    tags?: string;
    author?: string;
    description?: string;
    ocr_engine?: string;
  }) => {
    const formData = new FormData();
    formData.append('file', file);
    
    if (metadata) {
      Object.entries(metadata).forEach(([key, value]) => {
        if (value) formData.append(key, value);
      });
    }

    const response = await apiClient.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  // 批量上传
  uploadBatch: async (files: File[], metadata?: {
    category?: string;
    tags?: string;
    author?: string;
    description?: string;
    ocr_engine?: string;
  }) => {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    
    if (metadata) {
      Object.entries(metadata).forEach(([key, value]) => {
        if (value) formData.append(key, value);
      });
    }

    const response = await apiClient.post('/upload_batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  // 删除文档
  delete: async (docId: number) => {
    const response = await apiClient.delete(`/documents/${docId}`);
    return response.data;
  },

  // 删除所有文档
  deleteAll: async () => {
    const response = await apiClient.delete('/documents');
    return response.data;
  },

  // 清理 MinIO 数据
  cleanupMinIO: async (docId: number) => {
    const response = await apiClient.post(`/documents/${docId}/cleanup-minio`);
    return response.data;
  },
};











