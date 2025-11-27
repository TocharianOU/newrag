import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { documentAPI } from '../api/documents';

export default function HomePage() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [ocrEngine, setOcrEngine] = useState('easy');

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => {
      if (files.length === 1) {
        return documentAPI.upload(files[0], { ocr_engine: ocrEngine });
      }
      return documentAPI.uploadBatch(files, { ocr_engine: ocrEngine });
    },
    onSuccess: () => {
      alert('上传成功！');
      setSelectedFiles([]);
    },
    onError: (error) => {
      alert('上传失败：' + error);
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  };

  const handleUpload = () => {
    if (selectedFiles.length === 0) {
      alert('请先选择文件！');
      return;
    }
    uploadMutation.mutate(selectedFiles);
  };

  return (
    <div className="space-y-8">
      <div className="text-center">
        <h2 className="text-3xl font-bold text-gray-900 mb-4">
          文档上传
        </h2>
        <p className="text-gray-600">
          支持 PDF、图片、PPTX、DOCX 和 ZIP 文件
        </p>
      </div>

      <div className="bg-white rounded-lg shadow p-8">
        <div className="space-y-6">
          {/* File Input */}
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-12 text-center hover:border-blue-400 transition-colors">
            <Upload size={48} className="mx-auto text-gray-400 mb-4" />
            <label className="cursor-pointer">
              <span className="text-blue-600 hover:text-blue-700 font-medium">
                点击选择文件
              </span>
              <input
                type="file"
                multiple
                accept=".pdf,.jpg,.jpeg,.png,.pptx,.docx,.zip"
                onChange={handleFileChange}
                className="hidden"
              />
            </label>
            <p className="text-sm text-gray-500 mt-2">
              或拖拽文件到此处
            </p>
          </div>

          {/* Selected Files */}
          {selectedFiles.length > 0 && (
            <div className="space-y-2">
              <h3 className="font-medium text-gray-900">
                已选择 {selectedFiles.length} 个文件：
              </h3>
              <ul className="space-y-1">
                {selectedFiles.map((file, index) => (
                  <li key={index} className="text-sm text-gray-600">
                    📄 {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* OCR Engine Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              OCR 引擎
            </label>
            <select
              value={ocrEngine}
              onChange={(e) => setOcrEngine(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="easy">EasyOCR (推荐)</option>
              <option value="paddle">PaddleOCR</option>
            </select>
          </div>

          {/* Upload Button */}
          <button
            onClick={handleUpload}
            disabled={selectedFiles.length === 0 || uploadMutation.isPending}
            className="w-full bg-blue-600 text-white py-3 px-6 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {uploadMutation.isPending ? '上传中...' : '开始上传'}
          </button>
        </div>
      </div>
    </div>
  );
}

