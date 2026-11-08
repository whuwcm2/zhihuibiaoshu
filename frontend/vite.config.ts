import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // Electron loads dist/index.html via file://, so assets must use relative paths
  base: './',
  plugins: [react(), tailwindcss()],
})
