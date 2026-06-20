import { resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

// Backend the dev server proxies /api → FastAPI to. Defaults to :8000 for normal
// dev; the isolated e2e/smoke run sets VITE_API_PORT so its throwaway Vite (on a
// separate port) proxies to its own throwaway backend, never the user's :8000.
const API_PORT = process.env.VITE_API_PORT || '8000'

export default {
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://localhost:${API_PORT}`,
        changeOrigin: true,
      },
      '/ws': {
        target: `ws://localhost:${API_PORT}`,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main:            resolve(__dirname, 'index.html'),
        'cadnano-editor': resolve(__dirname, 'cadnano-editor.html'),
        'strand-anim':    resolve(__dirname, 'strand-anim.html'),
      },
    },
  },
}
