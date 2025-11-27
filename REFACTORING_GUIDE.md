# Web App 重构迁移指南

## ✅ 已完成的迁移

### 1. 已迁移的函数

| 原位置 | 新位置 | 函数名 |
|--------|--------|--------|
| app.py | handlers/document_processor.py | `extract_matched_bboxes_from_file()` |
| app.py | routes/document_routes.py | `list_documents()` |
| app.py | routes/cleanup_routes.py | `check_data_synchronization()` |

### 2. 已更新的导入

```python
# app.py 顶部已添加
from web.routes import document_router, cleanup_router
from web.handlers import extract_matched_bboxes_from_file

# app.py 初始化后已添加
app.include_router(document_router)
app.include_router(cleanup_router)
```

---

## 📋 待迁移函数清单

### 一、迁移到 `routes/document_routes.py` (文档管理路由)

**上传相关：**
- [ ] `upload_file()` - POST /upload
- [ ] `upload_batch()` - POST /upload_batch
- [ ] `upload_zip()` - POST /upload_zip

**文档管理：**
- [ ] `get_document_progress()` - GET /documents/{doc_id}/progress
- [ ] `delete_document()` - DELETE /documents/{doc_id}
- [ ] `delete_all_documents()` - DELETE /documents (批量删除)
- [ ] `cleanup_document_minio()` - POST /documents/{doc_id}/cleanup-minio
- [ ] `delete_documents()` - DELETE /documents (按过滤器删除)

**任务管理：**
- [ ] `list_tasks()` - GET /tasks
- [ ] `get_task()` - GET /tasks/{task_id}
- [ ] `pause_task()` - POST /tasks/{task_id}/pause
- [ ] `resume_task()` - POST /tasks/{task_id}/resume
- [ ] `cancel_task()` - POST /tasks/{task_id}/cancel
- [ ] `cleanup_tasks()` - POST /tasks/cleanup

---

### 二、迁移到 `routes/cleanup_routes.py` (数据清理路由)

**清理相关：**
- [ ] `cleanup_elasticsearch_orphans()` - POST /cleanup-elasticsearch
- [ ] `cleanup_minio_orphans()` - POST /cleanup-minio
- [ ] `cleanup_local_orphan_files()` - POST /cleanup-local-files

**孤岛检查：**
- [ ] `check_orphan_documents()` - GET /orphan-check
- [ ] `cleanup_orphan_documents()` - DELETE /orphan-cleanup
- [ ] `delete_es_document_by_id()` - POST /es-index/delete

---

### 三、迁移到 `handlers/document_processor.py` (文档处理逻辑)

**核心处理函数：**
- [ ] `process_single_pdf()` - PDF 处理逻辑
- [ ] `process_document_background()` - 后台处理入口

**注意：** 这两个函数很大（800+ 行），迁移时需要：
1. 将 `processing_semaphore` 也迁移过去
2. 确保所有依赖的导入都正确

---

### 四、保留在 `app.py` (不需要迁移)

**基础路由：**
- ✅ `index()` - GET / (首页)
- ✅ `search()` - POST /search (搜索)
- ✅ `search_component()` - GET /component/{component_id}
- ✅ `get_stats()` - GET /stats (统计)
- ✅ `health_check()` - GET /health

**Pydantic 模型：**
- ✅ `SearchRequest`
- ✅ `SearchResponse`
- ✅ `MetadataUpdate`

**全局变量：**
- ✅ `pipeline`
- ✅ `db`
- ✅ `upload_folder`
- ✅ `processed_folder`
- ✅ `templates`

---

## 🔧 迁移步骤

### 步骤 1: 迁移文档路由

```bash
# 1. 从 app.py 复制函数到 routes/document_routes.py
# 2. 添加必要的导入
# 3. 确保每个函数都是 @router.xxx 而不是 @app.xxx
# 4. 测试每个路由是否正常工作
```

**示例：迁移 upload_file()**

```python
# 在 routes/document_routes.py 中
from fastapi import File, Form, UploadFile
import hashlib

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    ocr_engine: Optional[str] = Form('easy')
):
    # 复制函数体...
    # 注意：需要导入 db, upload_folder, pipeline, task_manager 等
```

### 步骤 2: 迁移清理路由

```bash
# 1. 从 app.py 复制函数到 routes/cleanup_routes.py
# 2. 确保都是 @router.xxx
# 3. 测试清理功能
```

### 步骤 3: 迁移处理逻辑

```bash
# 1. 将 process_single_pdf 和 process_document_background 复制到
#    handlers/document_processor.py
# 2. 迁移 processing_semaphore
# 3. 更新所有导入
```

### 步骤 4: 更新依赖注入

某些函数需要访问 `db`, `pipeline`, `upload_folder` 等全局变量。

**方案 A：** 在每个路由文件中导入

```python
# routes/document_routes.py
from src.database import DatabaseManager
from src.pipeline import ProcessingPipeline

db = DatabaseManager()
pipeline = ProcessingPipeline()
```

**方案 B：** 使用 FastAPI Depends (更推荐)

```python
from fastapi import Depends

def get_db():
    return DatabaseManager()

@router.get("/documents")
async def list_documents(db: DatabaseManager = Depends(get_db)):
    # ...
```

---

## ⚠️ 注意事项

1. **导入路径问题**
   - 从 `app.py` 迁移后，import 路径可能需要调整
   - 特别注意相对导入 vs 绝对导入

2. **全局变量访问**
   - `db`, `pipeline`, `upload_folder`, `processed_folder`, `task_manager`
   - 需要在新文件中重新导入或初始化

3. **装饰器修改**
   - `@app.get()` → `@router.get()`
   - `@app.post()` → `@router.post()`
   - `@app.delete()` → `@router.delete()`

4. **测试每个迁移**
   - 迁移一个函数后立即测试
   - 确保 API 端点仍然可用

5. **处理循环导入**
   - 如果出现循环导入，考虑重新组织代码结构

---

## 🧪 测试检查清单

迁移完成后，测试以下功能：

**基础功能：**
- [ ] 访问首页 GET /
- [ ] 查看统计 GET /stats
- [ ] 文档列表 GET /documents

**上传功能：**
- [ ] 上传 PDF
- [ ] 上传图片
- [ ] 上传 PPTX
- [ ] 上传 ZIP

**删除功能：**
- [ ] 删除单个文档
- [ ] 清理 ES
- [ ] 清理 MinIO
- [ ] 清理本地文件

**同步检查：**
- [ ] 数据同步检查
- [ ] 孤岛检查

**任务管理：**
- [ ] 查看任务列表
- [ ] 暂停/恢复任务
- [ ] 取消任务

---

## 📊 预期结果

迁移完成后的文件大小：

| 文件 | 当前 | 目标 | 说明 |
|------|------|------|------|
| app.py | 2104 行 | ~300 行 | 只保留基础路由 |
| routes/document_routes.py | - | ~600 行 | 文档和任务管理 |
| routes/cleanup_routes.py | - | ~400 行 | 清理和同步 |
| handlers/document_processor.py | - | ~900 行 | 处理逻辑 |

**总计：** 2104 行 → 2200 行（增加注释和结构）

---

## 🚀 快速开始

```bash
# 1. 检查当前结构
ls -la web/routes/
ls -la web/handlers/

# 2. 开始迁移第一个函数（upload_file）
# 编辑 routes/document_routes.py

# 3. 测试
uv run python web/app.py

# 4. 验证 API
curl http://localhost:8080/documents
```

---

## ❓ 问题排查

**问题：ModuleNotFoundError**
```bash
# 确保在项目根目录运行
cd /Users/ablatazmat/Downloads/SmartResume
uv run python web/app.py
```

**问题：CircularImportError**
```python
# 延迟导入
def some_function():
    from web.handlers import something
    # ...
```

**问题：全局变量未定义**
```python
# 在路由文件顶部重新初始化
from src.database import DatabaseManager
db = DatabaseManager()
```

---

完成迁移后，记得提交到 Git！

```bash
git add -A
git commit -m "refactor: 拆分 app.py 为多个模块

- 迁移文档路由到 routes/document_routes.py
- 迁移清理路由到 routes/cleanup_routes.py  
- 迁移处理逻辑到 handlers/document_processor.py
- 减少主文件复杂度从 2100+ 行到 300 行"
git push
```
