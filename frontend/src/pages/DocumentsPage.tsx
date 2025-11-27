import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2, FileText, Calendar, Loader2, RefreshCw, Cloud } from 'lucide-react';
import { documentAPI } from '../api/documents';

export default function DocumentsPage() {
  const queryClient = useQueryClient();

  const { data, isLoading, isRefetching, refetch } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentAPI.list({ limit: 100 }),
  });

  // 完整删除
  const deleteMutation = useMutation({
    mutationFn: documentAPI.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  // 仅清理 MinIO
  const cleanupMinIOMutation = useMutation({
    mutationFn: documentAPI.cleanupMinIO,
    onSuccess: (data) => {
      alert(`MinIO 数据清理成功，释放了 ${data.files_deleted} 个文件`);
    },
  });

  const handleDelete = (docId: number, filename: string) => {
    if (confirm(`确定要删除文档 "${filename}" 吗？这将删除所有相关数据！`)) {
      deleteMutation.mutate(docId);
    }
  };
  
  const handleCleanupMinIO = (docId: number, filename: string) => {
    if (confirm(`确定要清理 "${filename}" 的 MinIO 数据吗？数据库记录将保留。`)) {
      cleanupMinIOMutation.mutate(docId);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <Loader2 className="w-10 h-10 text-indigo-600 animate-spin mb-4" />
        <p className="text-slate-500">正在加载文档库...</p>
      </div>
    );
  }

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
        <button 
          onClick={() => refetch()}
          className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-full transition-colors text-slate-500"
          title="刷新列表"
        >
          <RefreshCw size={20} className={isRefetching ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="card overflow-hidden bg-white dark:bg-slate-900 shadow-sm border border-slate-200 dark:border-slate-800 rounded-2xl">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
            <thead className="bg-slate-50/50 dark:bg-slate-800/50">
              <tr>
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
                <tr key={doc.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/30 transition-colors group">
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
                        : doc.status === 'processing'
                        ? 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-800 animate-pulse'
                        : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800'
                    }`}>
                      {doc.status === 'completed' && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5"></span>}
                      {doc.status === 'processing' && <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />}
                      {doc.status === 'failed' && <span className="w-1.5 h-1.5 rounded-full bg-rose-500 mr-1.5"></span>}
                      {doc.status}
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
                      {new Date(doc.created_at).toLocaleDateString('zh-CN')}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => handleCleanupMinIO(doc.id, doc.filename)}
                        className="p-2 text-purple-600 hover:bg-purple-50 dark:text-purple-400 dark:hover:bg-purple-900/20 rounded-lg transition-colors"
                        title="仅清理 MinIO 数据"
                      >
                        <Cloud size={18} />
                      </button>
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
                  <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                    暂无文档，请先上传
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
