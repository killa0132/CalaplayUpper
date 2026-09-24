import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The build lands in gui/dist, which FastAPI serves (and PyInstaller ships
// as a data file).  `base: './'` keeps the asset URLs relative so the app also
// works when the folder is opened through a sub-path.
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    assetsDir: 'assets',
    chunkSizeWarningLimit: 1500
  },
  server: {
    port: 5173,
    strictPort: false,
    // `npm run dev` serves the page from 5173 while the FastAPI backend listens
    // on another port, so /api is proxied through.  The dev backend uses a FIXED
    // port (`python gui_main.py --dev` -> 8756); override with CALA_API.
    proxy: {
      '/api': {
        target: process.env.CALA_API || 'http://127.0.0.1:8756',
        changeOrigin: false,
        ws: false
      }
    }
  }
})
