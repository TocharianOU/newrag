import { useQuery } from '@tanstack/react-query';
import { FileText, Database, HardDrive } from 'lucide-react';
import { statsAPI } from '../api/stats';

export default function StatsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: statsAPI.get,
    refetchInterval: 5000, // 每5秒刷新一次
  });

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-blue-600 border-t-transparent"></div>
        <p className="mt-4 text-gray-600">加载中...</p>
      </div>
    );
  }

  const stats = [
    {
      label: '总文档数',
      value: data?.total_documents || 0,
      icon: FileText,
      color: 'blue',
    },
    {
      label: '总数据块',
      value: data?.total_chunks || 0,
      icon: Database,
      color: 'green',
    },
    {
      label: '存储空间',
      value: `${data?.total_size_mb.toFixed(2) || 0} MB`,
      icon: HardDrive,
      color: 'purple',
    },
  ];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">
        系统统计
      </h2>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {stats.map((stat, index) => (
          <div
            key={index}
            className="bg-white rounded-lg shadow p-6"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600 mb-1">{stat.label}</p>
                <p className="text-3xl font-bold text-gray-900">{stat.value}</p>
              </div>
              <stat.icon 
                size={48} 
                className={`text-${stat.color}-600`}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Documents by Type */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          文档类型分布
        </h3>
        <div className="space-y-3">
          {Object.entries(data?.documents_by_type || {}).map(([type, count]) => (
            <div key={type} className="flex items-center justify-between">
              <span className="text-gray-700">{type}</span>
              <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                {count}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Documents by Status */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          文档状态分布
        </h3>
        <div className="space-y-3">
          {Object.entries(data?.documents_by_status || {}).map(([status, count]) => (
            <div key={status} className="flex items-center justify-between">
              <span className="text-gray-700">{status}</span>
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                status === 'completed'
                  ? 'bg-green-100 text-green-800'
                  : status === 'processing'
                  ? 'bg-yellow-100 text-yellow-800'
                  : 'bg-red-100 text-red-800'
              }`}>
                {count}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

