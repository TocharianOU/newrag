import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, Loader2, ArrowRight, Filter, X } from 'lucide-react';
import { searchAPI } from '../api/search';
import type { SearchRequest } from '../api/search';
import { SearchResultCard } from '../components/SearchResultCard';

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [filenameQuery, setFilenameQuery] = useState('');
  const [selectedFileType, setSelectedFileType] = useState<string>('');
  const [showFilters, setShowFilters] = useState(false);
  const [searchParams, setSearchParams] = useState<SearchRequest | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['search', searchParams],
    queryFn: () => searchAPI.search(searchParams!),
    enabled: !!searchParams,
  });

  const handleSearch = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    
    // Allow search if query exists OR if any filter is set
    if (query.trim() || filenameQuery.trim() || selectedFileType) {
      const filters: Record<string, any> = {};
      
      if (filenameQuery.trim()) {
        filters.filename = filenameQuery.trim();
      }
      
      if (selectedFileType) {
        filters.file_type = selectedFileType;
      }

      setSearchParams({
        query: query.trim(),
        k: 10,
        use_hybrid: true,
        filters: Object.keys(filters).length > 0 ? filters : undefined
      });
    }
  };

  const clearFilters = () => {
    setFilenameQuery('');
    setSelectedFileType('');
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Search Header */}
      <div className="text-center space-y-6 py-8">
        <h2 className="text-3xl font-bold text-slate-900 dark:text-slate-100">
          智能知识检索
        </h2>
        
        <div className="max-w-2xl mx-auto">
          <form onSubmit={handleSearch} className="relative group mb-4">
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
            <div className="absolute right-2 top-2 bottom-2 flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowFilters(!showFilters)}
                className={`p-2 rounded-xl transition-colors ${
                  showFilters || filenameQuery || selectedFileType
                    ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400'
                    : 'hover:bg-slate-100 text-slate-400 dark:hover:bg-slate-800'
                }`}
                title="高级筛选"
              >
                <Filter size={20} />
              </button>
              <button
                type="submit"
                disabled={(!query.trim() && !filenameQuery && !selectedFileType) || isLoading}
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-6 h-full rounded-xl font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isLoading ? <Loader2 className="animate-spin" size={18} /> : <ArrowRight size={18} />}
                <span>搜索</span>
              </button>
            </div>
          </form>

          {/* Filters Panel */}
          {(showFilters || filenameQuery || selectedFileType) && (
            <div className={`
              bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 
              animate-in fade-in slide-in-from-top-2 transition-all
              ${showFilters ? 'block' : 'hidden'}
            `}>
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium text-slate-500">高级筛选条件</span>
                {(filenameQuery || selectedFileType) && (
                  <button 
                    onClick={clearFilters}
                    className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
                  >
                    <X size={12} /> 清空筛选
                  </button>
                )}
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-slate-500 ml-1">文档名称</label>
                  <input
                    type="text"
                    value={filenameQuery}
                    onChange={(e) => setFilenameQuery(e.target.value)}
                    placeholder="输入文件名关键词..."
                    className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
                  />
                </div>
                
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-slate-500 ml-1">文件类型</label>
                  <select
                    value={selectedFileType}
                    onChange={(e) => setSelectedFileType(e.target.value)}
                    className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors appearance-none"
                  >
                    <option value="">所有类型</option>
                    <option value="pdf">PDF 文档</option>
                    <option value="docx">Word 文档 (.docx)</option>
                    <option value="doc">Word 文档 (.doc)</option>
                    <option value="pptx">PPT 演示文稿 (.pptx)</option>
                    <option value="ppt">PPT 演示文稿 (.ppt)</option>
                    <option value="xlsx">Excel 表格 (.xlsx)</option>
                    <option value="xls">Excel 表格 (.xls)</option>
                    <option value="odt">OpenDocument 文本 (.odt)</option>
                    <option value="ods">OpenDocument 表格 (.ods)</option>
                    <option value="odp">OpenDocument 演示 (.odp)</option>
                    <option value="md">Markdown 文档 (.md)</option>
                    <option value="txt">纯文本 (.txt)</option>
                    <option value="image">图片</option>
                  </select>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Results Area */}
      <div className="space-y-6 pb-12">
        {data && (
          <div className="flex items-center justify-between px-2 animate-in fade-in slide-in-from-bottom-2">
            <span className="text-sm font-medium text-slate-500">
              找到 {data.total} 个相关结果
            </span>
            <div className="flex gap-2">
              {filenameQuery && (
                <span className="text-xs px-2 py-1 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 rounded-md font-medium border border-indigo-100 dark:border-indigo-800">
                  文件: {filenameQuery}
                </span>
              )}
              {selectedFileType && (
                <span className="text-xs px-2 py-1 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 rounded-md font-medium border border-indigo-100 dark:border-indigo-800">
                  类型: {selectedFileType}
                </span>
              )}
              <span className="text-xs px-2 py-1 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 rounded-md font-medium border border-emerald-100 dark:border-emerald-800">
                混合检索
              </span>
            </div>
          </div>
        )}

        <div className="space-y-6">
          {data?.results.map((result, index) => (
            <div 
              key={index} 
              className="animate-in fade-in slide-in-from-bottom-4 fill-mode-both"
              style={{ animationDelay: `${index * 100}ms` }}
            >
              <SearchResultCard result={result} index={index} />
            </div>
          ))}
        </div>
        
        {data?.results.length === 0 && !isLoading && (
          <div className="text-center py-20 bg-slate-50 dark:bg-slate-900/50 rounded-3xl border border-dashed border-slate-300 dark:border-slate-700">
            <div className="inline-flex p-4 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400 mb-4">
              <Search size={32} />
            </div>
            <p className="text-lg font-medium text-slate-900 dark:text-slate-100">未找到相关内容</p>
            <p className="text-slate-500 mt-2">请尝试更换关键词或放宽筛选条件</p>
          </div>
        )}
      </div>
    </div>
  );
}
