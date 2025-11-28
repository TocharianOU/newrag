# NewRAG Frontend (React)

基于 React + TypeScript + Vite 的现代化前端。

## 技术栈

- **React 18** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具
- **Tailwind CSS** - 样式框架
- **React Router** - 路由管理
- **TanStack Query** - 数据获取和缓存
- **Axios** - HTTP 客户端
- **Lucide React** - 图标库

## 项目结构

```
src/
├── api/              # API 客户端
│   ├── client.ts     # Axios 配置
│   ├── documents.ts  # 文档 API
│   ├── search.ts     # 搜索 API
│   └── stats.ts      # 统计 API
├── components/       # 可复用组件
│   └── Layout.tsx    # 布局组件
├── pages/            # 页面组件
│   ├── HomePage.tsx      # 首页（上传）
│   ├── SearchPage.tsx    # 搜索页
│   ├── DocumentsPage.tsx # 文档列表
│   └── StatsPage.tsx     # 统计页
├── App.tsx          # 根组件
└── main.tsx         # 入口文件
```

## 开发

```bash
# 安装依赖
npm install

# 启动开发服务器（端口 3000）
npm run dev

# 构建生产版本
npm run build

# 预览生产版本
npm run preview
```

## 后端配置

开发模式下，前端会自动代理到后端（localhost:8080）。

生产模式下，前端和后端可以分开部署。

## 环境变量

创建 `.env` 文件：

```
VITE_API_URL=http://localhost:8080
```

## 功能

- ✅ 文档上传（单文件/批量）
- ✅ 文档搜索
- ✅ 文档管理（列表/删除）
- ✅ 系统统计
- ✅ 实时进度更新
- ✅ 响应式设计
