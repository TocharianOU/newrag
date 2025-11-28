import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 读取环境变量（由 dev.py 注入）
  const frontendPort = parseInt(process.env.FRONTEND_PORT || '3000')
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8080'

  console.log(`[Vite Config] Frontend Port: ${frontendPort}`)
  console.log(`[Vite Config] Backend Proxy Target: ${backendUrl}`)

  return {
    plugins: [react()],
    server: {
      port: frontendPort,
      strictPort: true, // 如果端口被占用，直接退出而不是尝试下一个端口
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''), // 关键：转发时去掉 /api 前缀
        },
        '/static': {
          target: backendUrl,
          changeOrigin: true,
        },
      }
    }
  }
})
