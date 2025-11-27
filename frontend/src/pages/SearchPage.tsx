import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, FileText, ChevronRight, Loader2, ArrowRight } from 'lucide-react';
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
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Search Header */}
      <div className="text-center space-y-6 py-8">
        <h2 className="text-3xl font-bold text-slate-900 dark:text-slate-100">
          智能知识检索
        </h2>
        
        <form onSubmit={handleSearch} className="relative max-w-2xl mx-auto group">
          <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none text-slate-400 group-focus-within:text-indigo-500 transition-colors">
            <Search size={20} />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入问题或关键词，例如：'系统架构是怎样的？'"
            className="w-full bg-white dark:bg-slate-900 border-2 border-slate-200 dark:border-slate-800 rounded-2xl py-4 pl-12 pr-32 text-lg outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 transition-all shadow-lg shadow-slate-200/50 dark:shadow-none"
          />
          <button
            type="submit"
            disabled={!query.trim() || isLoading}
            className="absolute right-2 top-2 bottom-2 bg-indigo-600 hover:bg-indigo-700 text-white px-6 rounded-xl font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading ? <Loader2 className="animate-spin" size={18} /> : <ArrowRight size={18} />}
            <span>搜索</span>
          </button>
        </form>
      </div>

      {/* Results Area */}
      <div className="space-y-6">
        {data && (
          <div className="flex items-center justify-between px-2">
            <span className="text-sm font-medium text-slate-500">
              找到 {data.total} 个相关结果
            </span>
            <span className="text-xs px-2 py-1 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 rounded-md font-medium">
              混合检索已启用
            </span>
          </div>
        )}

        {data?.results.map((result, index) => (
          <div
            key={index}
            className="group card p-6 hover:border-indigo-500/30 dark:hover:border-indigo-500/30 transition-all duration-300 animate-in fade-in slide-in-from-bottom-4 fill-mode-both"
            style={{ animationDelay: `${index * 50}ms` }}
          >
            <div className="flex justify-between items-start mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center text-indigo-600 dark:text-indigo-400 group-hover:scale-110 transition-transform duration-300">
                  <FileText size={20} />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900 dark:text-slate-100 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                    {result.metadata.filename || '未命名文档'}
                  </h3>
                  <div className="flex gap-2 text-xs text-slate-500 mt-1">
                    {result.metadata.page_number && (
                      <span className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-full">
                        第 {result.metadata.page_number} 页
                      </span>
                    )}
                    {result.metadata.category && (
                      <span className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-full">
                        {result.metadata.category}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              
              <div className="flex flex-col items-end">
                <div className="flex items-center gap-1 text-sm font-bold text-indigo-600 dark:text-indigo-400">
                  {(result.score * 100).toFixed(0)}%
                </div>
                <span className="text-xs text-slate-400">匹配度</span>
              </div>
            </div>
            
            <div className="bg-slate-50 dark:bg-slate-950/50 rounded-xl p-4 border border-slate-100 dark:border-slate-800/50">
              <p className="text-slate-700 dark:text-slate-300 leading-relaxed text-sm">
                {result.text}
              </p>
            </div>
            
            <div className="mt-4 flex justify-end opacity-0 group-hover:opacity-100 transition-opacity duration-200">
              <button className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1">
                查看详情 <ChevronRight size={14} />
              </button>
            </div>
          </div>
        ))}
        
        {data?.results.length === 0 && !isLoading && (
          <div className="text-center py-20 bg-slate-50 dark:bg-slate-900/50 rounded-3xl border border-dashed border-slate-300 dark:border-slate-700">
            <div className="inline-flex p-4 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400 mb-4">
              <Search size={32} />
            </div>
            <p className="text-lg font-medium text-slate-900 dark:text-slate-100">未找到相关内容</p>
            <p className="text-slate-500 mt-2">请尝试更换关键词重新搜索</p>
          </div>
        )}
      </div>
    </div>
  );
}
