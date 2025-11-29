import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2, FileText, Calendar, Loader2, RefreshCw, Cloud, CheckSquare, Square } from 'lucide-react';
import { documentAPI } from '../api/documents';

export default function DocumentsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [selectedDocs, setSelectedDocs] = useState<Set<number>>(new Set());

  const { data, isLoading, isRefetching, refetch } = useQuery({
    queryKey: ['documents', page, pageSize],
    queryFn: () => documentAPI.list({ limit: pageSize, offset: (page - 1) * pageSize }),
  });

  // 完整删除
  const deleteMutation = useMutation({
    mutationFn: documentAPI.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  const handleDelete = async (docId: number, filename: string) => {
    if (confirm(`确定要删除文档 "${filename}" 吗？这将删除所有相关数据！`)) {
      try {
        await deleteMutation.mutateAsync(docId);
      } catch (error) {
        console.error("删除失败", error);
        alert("删除失败，请查看控制台");
      }
    }
  };
  
  const handleBatchDelete = async () => {
    if (selectedDocs.size === 0) return;
    
    if (confirm(`确定要删除选中的 ${selectedDocs.size} 个文档吗？这将删除所有相关数据！`)) {
       const ids = Array.from(selectedDocs);
       let successCount = 0;
       
       // 简单的串行删除实现，实际项目中可能需要后端支持批量删除 API
       for (const id of ids) {
         try {
           await deleteMutation.mutateAsync(id);
           successCount++;
         } catch (error) {
           console.error(`删除文档 ${id} 失败`, error);
         }
       }
       
       alert(`批量删除完成。成功: ${successCount}, 失败: ${ids.length - successCount}`);
       setSelectedDocs(new Set()); // 清空选择
       queryClient.invalidateQueries({ queryKey: ['documents'] });
    }
  };

  const toggleSelectAll = () => {
    if (!data?.documents) return;
    
    if (selectedDocs.size === data.documents.length) {
      setSelectedDocs(new Set());
    } else {
      const newSet = new Set<number>();
      data.documents.forEach(doc => newSet.add(doc.id));
      setSelectedDocs(newSet);
    }
  };

  const toggleSelectDoc = (id: number) => {
    const newSet = new Set(selectedDocs);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    setSelectedDocs(newSet);
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <Loader2 className="w-10 h-10 text-indigo-600 animate-spin mb-4" />
        <p className="text-slate-500">正在加载文档库...</p>
      </div>
    );
  }

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
            文档库
          </h2>
          <p className="text-slate-500 text-sm mt-1">
            管理已上传的文档和知识库资源
          </p>
        </div>
        <div className="flex items-center gap-3">
            {selectedDocs.size > 0 && (
              <button
                onClick={handleBatchDelete}
                className="flex items-center gap-2 px-3 py-2 bg-rose-100 hover:bg-rose-200 text-rose-700 rounded-lg transition-colors text-sm font-medium"
              >
                <Trash2 size={16} />
                批量删除 ({selectedDocs.size})
              </button>
            )}
            <button 
              onClick={() => refetch()}
              className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-full transition-colors text-slate-500"
              title="刷新列表"
            >
              <RefreshCw size={20} className={isRefetching ? "animate-spin" : ""} />
            </button>
        </div>
      </div>

      <div className="card overflow-hidden bg-white dark:bg-slate-900 shadow-sm border border-slate-200 dark:border-slate-800 rounded-2xl">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
            <thead className="bg-slate-50/50 dark:bg-slate-800/50">
              <tr>
                <th className="px-4 py-4 w-12">
                  <button 
                    onClick={toggleSelectAll}
                    className="text-slate-400 hover:text-indigo-600 transition-colors"
                  >
                    {data?.documents.length && selectedDocs.size === data.documents.length ? (
                        <CheckSquare size={20} className="text-indigo-600" />
                    ) : (
                        <Square size={20} />
                    )}
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  文档名称
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  状态
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  元数据
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  上传时间
                </th>
                <th className="px-6 py-4 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {data?.documents.map((doc) => (
                <tr key={doc.id} className={`hover:bg-slate-50/80 dark:hover:bg-slate-800/30 transition-colors group ${selectedDocs.has(doc.id) ? 'bg-indigo-50/30 dark:bg-indigo-900/10' : ''}`}>
                  <td className="px-4 py-4">
                     <button 
                        onClick={() => toggleSelectDoc(doc.id)}
                        className="text-slate-400 hover:text-indigo-600 transition-colors"
                      >
                        {selectedDocs.has(doc.id) ? (
                            <CheckSquare size={20} className="text-indigo-600" />
                        ) : (
                            <Square size={20} />
                        )}
                      </button>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mr-4">
                        <FileText size={20} />
                      </div>
                      <div>
                        <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {doc.filename}
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          {(doc.file_size / 1024 / 1024).toFixed(2)} MB • {doc.file_type.toUpperCase()}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${
                      doc.status === 'completed' 
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800'
                        : (doc.status === 'processing' || doc.status === 'pending')
                        ? 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-800 animate-pulse'
                        : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800'
                    }`}>
                      {doc.status === 'completed' && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5"></span>}
                      {(doc.status === 'processing' || doc.status === 'pending') && <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />}
                      {doc.status === 'failed' && <span className="w-1.5 h-1.5 rounded-full bg-rose-500 mr-1.5"></span>}
                      {doc.status === 'pending' ? 'processing' : doc.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex flex-col gap-1">
                      {doc.total_pages ? (
                        <span className="text-xs text-slate-500 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded w-fit">
                          {doc.total_pages} 页
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">-</span>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center text-sm text-slate-500">
                      <Calendar size={14} className="mr-1.5" />
                      {doc.created_at ? new Date(doc.created_at).toLocaleDateString('zh-CN') : '-'}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => handleDelete(doc.id, doc.filename)}
                        className="p-2 text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-900/20 rounded-lg transition-colors"
                        title="完整删除"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {data?.documents.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                    暂无文档，请先上传
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      
      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
            <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-50"
            >
                上一页
            </button>
            <span className="px-3 py-1 text-slate-600 dark:text-slate-400">
                第 {page} / {totalPages} 页
            </span>
            <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-50"
            >
                下一页
            </button>
        </div>
      )}
    </div>
  );
}
