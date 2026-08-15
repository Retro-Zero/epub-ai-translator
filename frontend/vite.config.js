import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/upload': 'http://127.0.0.1:8000',
      '/jobs': 'http://127.0.0.1:8000',
      '/translate': 'http://127.0.0.1:8000',
      '/glossary': 'http://127.0.0.1:8000',
      '/qa': 'http://127.0.0.1:8000',
      '/finalize': 'http://127.0.0.1:8000',
      '/download': 'http://127.0.0.1:8000',
      '/settings': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
});
