import { useState, useRef, useEffect } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Upload, FileType, X, CheckCircle2, AlertCircle, FileText, Image as ImageIcon, FileCode, Sparkles, Shield } from 'lucide-react';
import { documentAPI } from '../api/documents';
import { getAccessToken } from '../utils/auth';

export default function HomePage() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [ocrEngine, setOcrEngine] = useState('vision');
  const [processingMode, setProcessingMode] = useState<string>('fast');
  const [isDragging, setIsDragging] = useState(false);
  const [visibility, setVisibility] = useState<string>('organization');
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch current user info
  const { data: userInfo } = useQuery({
    queryKey: ['currentUser'],
    queryFn: async () => {
      const token = getAccessToken();
      if (!token) return null;
      
      const response = await fetch('/api/auth/me', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (!response.ok) return null;
      return response.json();
    }
  });

  // Set default organization when user info is loaded
  useEffect(() => {
    if (userInfo?.org_id && !selectedOrgId) {
      setSelectedOrgId(userInfo.org_id);
    }
  }, [userInfo, selectedOrgId]);

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => {
      const metadata = {
        ocr_engine: ocrEngine,
        processing_mode: processingMode,
        organization_id: selectedOrgId || undefined,
        visibility: visibility
      };
      
      if (files.length === 1) {
        return documentAPI.upload(files[0], metadata);
      }
      return documentAPI.uploadBatch(files, metadata);
    },
    onSuccess: () => {
      setSelectedFiles([]);
      // 可以添加一个 toast 通知
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(prev => [...prev, ...Array.from(e.target.files!)]);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files) {
      setSelectedFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]);
    }
  };

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const getFileIcon = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    if (['jpg', 'jpeg', 'png'].includes(ext || '')) return <ImageIcon className="text-purple-500" />;
    if (['pdf'].includes(ext || '')) return <FileText className="text-red-500" />;
    if (['pptx', 'odp'].includes(ext || '')) return <FileCode className="text-orange-500" />; // Presentation
    if (['docx', 'odt'].includes(ext || '')) return <FileText className="text-blue-500" />;
    if (['xlsx', 'xls', 'ods'].includes(ext || '')) return <FileText className="text-green-500" />;
    return <FileType className="text-slate-500" />;
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header Section */}
      <div className="text-center py-8">
        <h2 className="text-4xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-violet-600 dark:from-indigo-400 dark:to-violet-400">
          上传文档
        </h2>
      </div>

      <div className="grid gap-8 md:grid-cols-[2fr,1fr]">
        {/* Main Upload Area */}
        <div className="space-y-6">
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`
              relative group cursor-pointer
              border-2 border-dashed rounded-3xl p-12 text-center transition-all duration-300
              ${isDragging 
                ? 'border-indigo-500 bg-indigo-50/50 dark:bg-indigo-900/20 scale-[1.02]' 
                : 'border-slate-300 dark:border-slate-700 hover:border-indigo-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'
              }
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.jpg,.jpeg,.png,.pptx,.docx,.zip,.odt,.ods,.odp"
              onChange={handleFileChange}
              className="hidden"
            />
            
            <div className="relative z-10 flex flex-col items-center gap-4">
              <div className={`
                w-20 h-20 rounded-2xl flex items-center justify-center shadow-xl transition-transform duration-300 group-hover:scale-110
                ${isDragging ? 'bg-indigo-100 text-indigo-600' : 'bg-white dark:bg-slate-800 text-slate-400 group-hover:text-indigo-500'}
              `}>
                <Upload size={40} strokeWidth={1.5} />
              </div>
              <div>
                <p className="text-xl font-semibold text-slate-700 dark:text-slate-200">
                  点击或拖拽文件
                </p>
                <p className="text-xs text-slate-400 mt-2">
                  PDF · DOCX · PPTX · XLSX · JPG · PNG · ZIP
                </p>
              </div>
            </div>
          </div>

          {/* File List */}
          {selectedFiles.length > 0 && (
            <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
              <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
                <span className="font-medium text-sm text-slate-600 dark:text-slate-400">已选择 {selectedFiles.length} 个文件</span>
                <button 
                  onClick={() => setSelectedFiles([])}
                  className="text-xs text-red-500 hover:text-red-600 font-medium"
                >
                  清空列表
                </button>
              </div>
              <div className="max-h-[300px] overflow-y-auto p-2 space-y-2">
                {selectedFiles.map((file, index) => (
                  <div key={index} className="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors group">
                    <div className="w-10 h-10 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                      {getFileIcon(file.name)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{file.name}</p>
                      <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); removeFile(index); }}
                      className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-full transition-all opacity-0 group-hover:opacity-100"
                    >
                      <X size={16} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Settings Sidebar */}
        <div className="space-y-6">
          <div className="card p-6 space-y-6 sticky top-24">
            <div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4 flex items-center gap-2">
                <Sparkles size={18} className="text-indigo-500" />
                设置
              </h3>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    OCR 引擎
                  </label>
                  <select
                    value={ocrEngine}
                    onChange={(e) => setOcrEngine(e.target.value)}
                    className="input-field w-full appearance-none"
                  >
                    <option value="vision">Apple Vision (推荐)</option>
                    <option value="paddle">PaddleOCR</option>
                    <option value="easy">EasyOCR</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    处理模式
                  </label>
                  <select
                    value={processingMode}
                    onChange={(e) => setProcessingMode(e.target.value)}
                    className="input-field w-full appearance-none"
                  >
                    <option value="fast">快速 (推荐)</option>
                    <option value="deep">深度</option>
                  </select>
                </div>

                {/* Permissions Settings */}
                <div className="pt-4 border-t border-slate-200 dark:border-slate-800">
                  <div className="flex items-center gap-2 mb-3">
                    <Shield size={16} className="text-indigo-500" />
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                      权限
                    </label>
                  </div>
                  
                  <div className="space-y-3">
                    <div>
                      <select
                        value={visibility}
                        onChange={(e) => setVisibility(e.target.value)}
                        className="input-field w-full appearance-none text-sm"
                      >
                        <option value="private">仅自己</option>
                        <option value="organization">组织内</option>
                        {userInfo?.is_superuser && (
                          <option value="public">公开</option>
                        )}
                      </select>
                    </div>

                    {userInfo && (userInfo.is_superuser || (userInfo.organizations && userInfo.organizations.length > 1)) && (
                      <div>
                        <select
                          value={selectedOrgId || ''}
                          onChange={(e) => setSelectedOrgId(Number(e.target.value))}
                          className="input-field w-full appearance-none text-sm"
                        >
                          {userInfo.organizations?.map((org: any) => (
                            <option key={org.id} value={org.id}>
                              {org.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-200 dark:border-slate-800">
              <button
                onClick={() => uploadMutation.mutate(selectedFiles)}
                disabled={selectedFiles.length === 0 || uploadMutation.isPending}
                className={`
                  w-full btn-primary py-3 text-lg
                  ${(selectedFiles.length === 0 || uploadMutation.isPending) ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                {uploadMutation.isPending ? (
                  <>
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>上传中...</span>
                  </>
                ) : (
                  <>
                    <Upload size={20} />
                    <span>上传</span>
                  </>
                )}
              </button>
            </div>

            {/* Status Messages */}
            {uploadMutation.isSuccess && (
              <div className="flex items-center gap-2 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-900 rounded-lg text-green-800 dark:text-green-200">
                <CheckCircle2 size={16} />
                <p className="text-sm font-medium">上传成功</p>
              </div>
            )}
            
            {uploadMutation.isError && (
              <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900 rounded-lg text-red-800 dark:text-red-200">
                <AlertCircle size={16} />
                <p className="text-sm font-medium">上传失败</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
