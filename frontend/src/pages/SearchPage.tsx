import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { searchAPI } from '../api/search';
import type { SearchRequest } from '../api/search';

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [searchParams, setSearchParams] = useState<SearchRequest | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['search', searchParams],
    queryFn: () => searchAPI.search(searchParams!),
    enabled: !!searchParams,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      setSearchParams({
        query: query.trim(),
        k: 10,
        use_hybrid: true,
      });
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <form onSubmit={handleSearch} className="flex gap-4">
          <div className="flex-1">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索文档内容..."
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <button
            type="submit"
            className="bg-blue-600 text-white px-8 py-3 rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center gap-2"
          >
            <Search size={20} />
            搜索
          </button>
        </form>
      </div>

      {isLoading && (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-blue-600 border-t-transparent"></div>
          <p className="mt-4 text-gray-600">搜索中...</p>
        </div>
      )}

      {data && (
        <div className="space-y-4">
          <div className="text-gray-600">
            找到 {data.total} 个结果
          </div>

          {data.results.map((result, index) => (
            <div
              key={index}
              className="bg-white rounded-lg shadow p-6 hover:shadow-md transition-shadow"
            >
              <div className="flex justify-between items-start mb-3">
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-gray-900 mb-1">
                    📄 {result.metadata.filename || '未命名文档'}
                  </h3>
                  <div className="flex gap-2 text-sm text-gray-500">
                    {result.metadata.page_number && (
                      <span>第 {result.metadata.page_number} 页</span>
                    )}
                    {result.metadata.category && (
                      <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs">
                        {result.metadata.category}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-sm font-medium text-blue-600">
                  相关度: {(result.score * 100).toFixed(1)}%
                </div>
              </div>
              
              <p className="text-gray-700 leading-relaxed">
                {result.text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

