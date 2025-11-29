import React, { useState, useEffect, useRef } from 'react';
import { FileText, ChevronDown, ChevronUp, Eye, Image as ImageIcon, Search, AlertCircle, ExternalLink, Maximize2, X, Trash2 } from 'lucide-react';
import type { SearchResult, PageData } from '../api/search';
import { documentAPI } from '../api/documents';

interface SearchResultCardProps {
  result: SearchResult;
  index: number;
  onDelete?: (id: string) => void;
}

export const SearchResultCard: React.FC<SearchResultCardProps> = ({ result, index, onDelete }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showImages, setShowImages] = useState(false);
  const [activeImageTab, setActiveImageTab] = useState<'original' | 'visualized'>('original');
  const [isLightboxOpen, setIsLightboxOpen] = useState(false);
  const [lightboxMode, setLightboxMode] = useState<'original' | 'visualized'>('original');
  const [isDeleting, setIsDeleting] = useState(false);
  const [isDeleted, setIsDeleted] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const handleDelete = async () => {
    if (!window.confirm('确定要删除这条记录吗？这将从数据库和索引中永久移除。')) return;
    
    const docIdStr = result.metadata.document_id || result.metadata.doc_id || result.id;
    if (!docIdStr) {
      alert('无法获取文档ID');
      return;
    }

    setIsDeleting(true);
    try {
      // 尝试将 ID 转换为数字，如果不是数字则可能无法调用 delete API (取决于 API 定义)
      // 目前 API 文档显示 delete 接收 number。ES 中的 ID 可能是 string。
      // 如果 docIdStr 是纯数字字符串，parseInt 可以工作。
      const docId = parseInt(docIdStr.toString(), 10);
      
      if (isNaN(docId)) {
        // 如果是非数字 ID（可能是旧数据），可能无法通过常规 API 删除
        console.warn('Document ID is not a number:', docIdStr);
        alert(`文档 ID 格式不正确 (${docIdStr})，无法通过 API 删除`);
        return;
      }

      await documentAPI.delete(docId);
      setIsDeleted(true);
      if (onDelete) onDelete(docIdStr.toString());
    } catch (error) {
      console.error('Delete failed', error);
      alert('删除失败，请查看控制台');
    } finally {
      setIsDeleting(false);
    }
  };

  if (isDeleted) return null;

  // Determine display text
  const fullContent = result.content || result.text || '';
  const highlightedContent = result.highlighted || '';
  const displayText = isExpanded ? fullContent : (highlightedContent || fullContent.substring(0, 300) + (fullContent.length > 300 ? '...' : ''));
  const hasLongContent = fullContent.length > 300;

  // Extract metadata
  const filename = result.metadata.filename || '未命名文档';
  const pageNumber = result.metadata.page_number || result.metadata.page || 1;
  const score = (result.score * 100).toFixed(1);
  const pagesData = result.metadata.pages_data || [];
  const ocrEngine = result.metadata.ocr_engine || 'standard';
  
  // Determine document download URL
  // Priority: 1. original_file_url (MinIO/S3) -> 2. Local download API
  let downloadUrl = '';
  if (result.metadata.original_file_url) {
    downloadUrl = result.metadata.original_file_url;
  } else if (result.metadata.source || result.metadata.filepath) {
    const path = result.metadata.source || result.metadata.filepath;
    downloadUrl = `/api/documents/download?path=${encodeURIComponent(path)}`;
  }

  // Find matching page data
  const matchedPage = pagesData.find(p => p.page_num === pageNumber) || pagesData[0];

  // Canvas drawing logic function
  const drawCanvas = (canvas: HTMLCanvasElement, isLargeView: boolean = false) => {
    const ctx = canvas.getContext('2d');
    if (!ctx || !matchedPage) return;

    const img = new Image();
    img.crossOrigin = "Anonymous"; // Handle potential CORS issues
    img.src = matchedPage.image_path;
    
    img.onload = () => {
      // Set canvas dimensions to match image
      canvas.width = img.width;
      canvas.height = img.height;
      
      // Draw image
      ctx.drawImage(img, 0, 0);
      
      // Draw matched bboxes
      if (result.matched_bboxes && result.matched_bboxes.length > 0) {
        // Scale styles for larger views if needed, though image coordinates are absolute
        const lineWidth = isLargeView ? 5 : 3; 
        const fontSize = isLargeView ? 32 : 24;
        const padding = 5; // Padding around text
        
        ctx.lineWidth = lineWidth;
        ctx.font = `bold ${fontSize}px Arial`;
        
        result.matched_bboxes.forEach((match, idx) => {
          let [x1, y1, x2, y2] = match.bbox;
          
          // Add padding to bbox
          x1 = Math.max(0, x1 - padding);
          y1 = Math.max(0, y1 - padding);
          x2 = Math.min(img.width, x2 + padding);
          y2 = Math.min(img.height, y2 + padding);

          const w = x2 - x1;
          const h = y2 - y1;
          
          // Draw rectangle
          ctx.strokeStyle = "red";
          ctx.strokeRect(x1, y1, w, h);
          
          // Draw background for number
          const badgeSize = isLargeView ? 40 : 30;
          ctx.fillStyle = "rgba(255, 0, 0, 0.8)";
          ctx.fillRect(x1, y1 - badgeSize, badgeSize, badgeSize);
          
          // Draw number
          ctx.fillStyle = "white";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText((idx + 1).toString(), x1 + badgeSize/2, y1 - badgeSize/2);
        });
      }
    };

    img.onerror = () => {
      // Draw error placeholder
      canvas.width = 400;
      canvas.height = 300;
      ctx.fillStyle = "#f3f4f6";
      ctx.fillRect(0, 0, 400, 300);
      ctx.fillStyle = "#6b7280";
      ctx.font = "16px Arial";
      ctx.textAlign = "center";
      ctx.fillText("图片加载失败", 200, 150);
    };
  };

  // Effect for inline canvas
  useEffect(() => {
    if (showImages && matchedPage && activeImageTab === 'original' && canvasRef.current) {
      drawCanvas(canvasRef.current, false);
    }
  }, [showImages, matchedPage, activeImageTab, result.matched_bboxes]);

  // Effect for lightbox canvas is handled via ref callback in render or separate component
  // For simplicity, we'll use a ref for the lightbox canvas too
  const lightboxCanvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (isLightboxOpen && matchedPage && lightboxMode === 'original' && lightboxCanvasRef.current) {
      drawCanvas(lightboxCanvasRef.current, true);
    }
  }, [isLightboxOpen, matchedPage, lightboxMode, result.matched_bboxes]);

  const openLightbox = (mode: 'original' | 'visualized') => {
    setLightboxMode(mode);
    setIsLightboxOpen(true);
  };


  return (
    <>
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-lg hover:shadow-xl transition-shadow p-6 border-l-4 border-indigo-500">
        {/* Header */}
        <div className="flex justify-between items-start mb-4">
          <div>
            <div className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-1 flex items-center gap-2">
              <FileText className="text-slate-500" size={20} />
              {filename}
            </div>
            <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-400">
              <span className="font-semibold bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">#{index + 1}</span>
              {pageNumber && (
                <span>• 第 <span className="font-bold text-indigo-600 dark:text-indigo-400">{pageNumber}</span> 页</span>
              )}
              {result.metadata.filepath && (
                <span className="truncate max-w-md" title={result.metadata.filepath}>• 📁 {result.metadata.filepath}</span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">相关度</div>
            <div className="text-lg font-bold text-emerald-600 dark:text-emerald-400">{score}%</div>
          </div>
        </div>

        {/* Content Preview */}
        <div className="mb-3">
          <div className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2 flex items-center gap-2">
            <Search size={16} /> 匹配内容:
          </div>
          <div className="bg-amber-50 dark:bg-amber-900/10 border-l-4 border-amber-400 p-4 rounded-r-lg">
            <div 
              className="text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap text-sm font-mono"
              dangerouslySetInnerHTML={{ __html: displayText }}
            />
            
            {hasLongContent && (
              <button 
                onClick={() => setIsExpanded(!isExpanded)}
                className="mt-2 text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 text-sm font-medium flex items-center gap-1"
              >
                {isExpanded ? (
                  <>
                    <ChevronUp size={14} /> 收起内容
                  </>
                ) : (
                  <>
                    <ChevronDown size={14} /> 显示完整内容
                  </>
                )}
              </button>
            )}
          </div>

          {/* Matched BBoxes List */}
          {result.matched_bboxes && result.matched_bboxes.length > 0 && (
            <div className="mt-2 p-2 bg-rose-50 dark:bg-rose-900/10 rounded border border-rose-200 dark:border-rose-800/30">
              <div className="text-xs font-semibold text-rose-700 dark:text-rose-400 mb-1">
                🎯 {result.matched_bboxes.length} 个匹配位置
              </div>
              <div className="text-xs text-slate-700 dark:text-slate-300 flex flex-wrap gap-2">
                {result.matched_bboxes.slice(0, 5).map((match, idx) => (
                  <span key={idx} className="inline-flex items-center bg-white dark:bg-slate-800 px-2 py-1 rounded border border-rose-100 dark:border-rose-800">
                    <span className="font-bold text-rose-600 dark:text-rose-400 mr-1">{idx + 1}.</span>
                    <span className="truncate max-w-[100px]">{match.text}</span>
                    <span className="text-slate-400 ml-1">({(match.confidence * 100).toFixed(0)}%)</span>
                  </span>
                ))}
                {result.matched_bboxes.length > 5 && (
                  <span className="text-rose-600 font-semibold text-xs py-1">+ {result.matched_bboxes.length - 5} 更多</span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Metadata Tags */}
        <div className="flex gap-2 flex-wrap mb-4">
          {result.metadata.category && (
            <span className="px-3 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 text-xs font-semibold rounded-full">
              📂 {result.metadata.category}
            </span>
          )}
          {result.metadata.author && (
            <span className="px-3 py-1 bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 text-xs font-semibold rounded-full">
              👤 {result.metadata.author}
            </span>
          )}
          {result.metadata.file_type && (
            <span className="px-3 py-1 bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-300 text-xs font-semibold rounded-full">
              📎 {result.metadata.file_type.toUpperCase()}
            </span>
          )}
          {/* OCR Confidence */}
          {result.metadata.avg_ocr_confidence !== undefined && result.metadata.avg_ocr_confidence > 0 && (
            <span className={`px-3 py-1 text-xs font-semibold rounded-full ${
              result.metadata.avg_ocr_confidence >= 0.85 
                ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-300'
                : result.metadata.avg_ocr_confidence >= 0.7
                ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300'
                : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300'
            }`}>
              🎯 置信度: {(result.metadata.avg_ocr_confidence * 100).toFixed(0)}%
            </span>
          )}
          {/* Document Link */}
          {downloadUrl && (
            <a 
              href={downloadUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-900/20 dark:hover:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 text-xs font-semibold rounded-full flex items-center gap-1 transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink size={10} /> 查看原文档
            </a>
          )}
        </div>

        {/* Image Preview Section */}
        {matchedPage && (
          <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-4">
            <div className="flex justify-between items-center mb-3">
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                📄 <span className="font-bold text-indigo-600 dark:text-indigo-400">第 {matchedPage.page_num} 页</span> / {pagesData.length} 页 | 
                引擎: <span className="font-bold text-green-600">{ocrEngine.toUpperCase()}</span> | 
                {matchedPage.text_count || 0} 个文本块
              </div>
              <button 
                onClick={() => setShowImages(!showImages)}
                className={`px-3 py-1.5 rounded text-sm transition-colors flex items-center gap-2 ${
                  showImages 
                    ? 'bg-slate-200 dark:bg-slate-700 text-slate-800 dark:text-slate-200' 
                    : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                }`}
              >
                {showImages ? (
                  <>隐藏预览</>
                ) : (
                  <><Eye size={16} /> 查看预览</>
                )}
              </button>
            </div>

            {showImages && (
              <div className="mt-4 animate-in fade-in duration-300">
                <div className="flex gap-2 mb-3">
                   <button 
                    onClick={() => setActiveImageTab('original')}
                    className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                      activeImageTab === 'original' 
                        ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300' 
                        : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`}
                  >
                    📷 原始页面 (带标注)
                  </button>
                  <button 
                    onClick={() => setActiveImageTab('visualized')}
                    className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                      activeImageTab === 'visualized' 
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300' 
                        : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`}
                  >
                    🔍 OCR 结果可视化
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Canvas View (Original + BBoxes) */}
                  <div className={`bg-slate-50 dark:bg-slate-950 p-2 rounded border border-slate-200 dark:border-slate-800 ${activeImageTab === 'original' ? 'block' : 'hidden md:block'}`}>
                    <div className="flex justify-between items-center mb-2">
                       <div className="text-xs font-semibold text-slate-500 text-center flex-1">原始页面</div>
                       <button 
                        onClick={() => openLightbox('original')}
                        className="text-slate-400 hover:text-indigo-600 transition-colors"
                        title="全屏查看"
                       >
                         <Maximize2 size={14} />
                       </button>
                    </div>
                    <div 
                      className="relative w-full overflow-hidden rounded border border-slate-200 dark:border-slate-700 cursor-zoom-in"
                      onClick={() => openLightbox('original')}
                    >
                      <canvas 
                        ref={canvasRef}
                        className="w-full h-auto block"
                        style={{ maxHeight: '600px', objectFit: 'contain' }}
                      />
                    </div>
                  </div>

                  {/* Visualized View */}
                  <div className={`bg-slate-50 dark:bg-slate-950 p-2 rounded border border-slate-200 dark:border-slate-800 ${activeImageTab === 'visualized' ? 'block' : 'hidden md:block'}`}>
                    <div className="flex justify-between items-center mb-2">
                      <div className="text-xs font-semibold text-slate-500 text-center flex-1">OCR 可视化结果</div>
                      <button 
                        onClick={() => openLightbox('visualized')}
                        className="text-slate-400 hover:text-indigo-600 transition-colors"
                        title="全屏查看"
                       >
                         <Maximize2 size={14} />
                       </button>
                    </div>
                    <div 
                      className="relative w-full overflow-hidden rounded border border-slate-200 dark:border-slate-700 cursor-zoom-in"
                      onClick={() => openLightbox('visualized')}
                    >
                      <img 
                        src={matchedPage.visualized_path} 
                        alt={`Visualization Page ${matchedPage.page_num}`}
                        className="w-full h-auto block"
                        style={{ maxHeight: '600px', objectFit: 'contain' }}
                        onError={(e) => {
                          (e.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22400%22 height=%22300%22><rect width=%22100%25%22 height=%22100%25%22 fill=%22%23f3f4f6%22/><text x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 fill=%22%236b7280%22>可视化未找到</text></svg>';
                        }}
                      />
                    </div>
                  </div>
                </div>

                {/* Components Tags */}
                {matchedPage.components && matchedPage.components.length > 0 && (
                  <div className="mt-4 p-3 bg-purple-50 dark:bg-purple-900/10 rounded-lg border border-purple-100 dark:border-purple-800/30">
                    <div className="flex gap-2 flex-wrap items-center">
                      <span className="text-xs font-bold text-purple-900 dark:text-purple-300 uppercase tracking-wider">
                        🔧 检测到的组件:
                      </span>
                      {matchedPage.components.slice(0, 15).map((c, i) => (
                        <span key={i} className="px-2 py-1 bg-purple-200 dark:bg-purple-800/50 text-purple-900 dark:text-purple-200 text-xs rounded font-mono shadow-sm">
                          {c}
                        </span>
                      ))}
                      {matchedPage.components.length > 15 && (
                        <span className="text-xs text-purple-700 dark:text-purple-400 font-semibold">
                          +{matchedPage.components.length - 15} 更多
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {/* Orphan Document State */}
        {!matchedPage && (
          <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-4">
            <div className="bg-red-50 dark:bg-red-900/10 rounded-lg p-4 border border-red-100 dark:border-red-800/30 flex items-start gap-3">
              <AlertCircle className="text-red-600 dark:text-red-400 shrink-0 mt-0.5" size={18} />
              <div className="flex-1">
                <div className="flex justify-between items-start">
                  <div>
                    <h4 className="text-sm font-bold text-red-700 dark:text-red-400">无页面预览</h4>
                    <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                      文档文件可能已被删除，或者 Elasticsearch 索引数据与数据库不一致。
                    </p>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete();
                    }}
                    disabled={isDeleting}
                    className="flex items-center gap-1 px-3 py-1.5 bg-red-100 hover:bg-red-200 dark:bg-red-900/40 dark:hover:bg-red-900/60 text-red-700 dark:text-red-300 rounded text-xs font-medium transition-colors disabled:opacity-50"
                  >
                    <Trash2 size={14} />
                    {isDeleting ? '删除中...' : '删除记录'}
                  </button>
                </div>
                
                <div className="mt-3">
                   <details className="text-xs">
                    <summary className="cursor-pointer text-indigo-600 dark:text-indigo-400 font-medium hover:underline">查看元数据详情</summary>
                    <pre className="mt-2 p-2 bg-slate-100 dark:bg-slate-800 rounded overflow-x-auto text-slate-600 dark:text-slate-400">
                      {JSON.stringify(result.metadata, null, 2)}
                    </pre>
                  </details>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Lightbox Modal */}
      {isLightboxOpen && matchedPage && (
        <div className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="absolute top-4 right-4 flex gap-4">
             <button 
              onClick={() => setIsLightboxOpen(false)}
              className="text-white/70 hover:text-white transition-colors bg-white/10 p-2 rounded-full"
            >
              <X size={24} />
            </button>
          </div>
          
          <div className="w-full max-w-7xl max-h-[90vh] overflow-auto flex justify-center">
            {lightboxMode === 'original' ? (
               <canvas 
                  ref={lightboxCanvasRef}
                  className="max-w-full h-auto object-contain"
                />
            ) : (
              <img 
                src={matchedPage.visualized_path} 
                alt="Full screen preview" 
                className="max-w-full h-auto object-contain"
              />
            )}
          </div>
        </div>
      )}
    </>
  );
};

