import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Built files are copied into home-server/axella/ and served at /axella/ – so relative asset paths.
export default defineConfig({
  base: './',
  define: { __AX_BUILD__: JSON.stringify(new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '')) },
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  build: { outDir: 'dist', emptyOutDir: true, assetsDir: 'assets', sourcemap: false },
})
