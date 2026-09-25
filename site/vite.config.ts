import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import type { InlineConfig } from 'vitest';
import { defineConfig, loadEnv } from 'vite';

declare module 'vite' {
  interface UserConfig {
    test?: InlineConfig;
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  return {
    plugins: [react()],
    build: {
      rollupOptions: {
        input: {
          catalog: fileURLToPath(new URL('./index.html', import.meta.url)),
          operator: fileURLToPath(new URL('./operator.html', import.meta.url)),
          research: fileURLToPath(new URL('./research.html', import.meta.url))
        }
      }
    },
    server: {
      proxy: {
        '/api': {
          target: env.VITE_BACKEND_URL?.trim() || 'http://127.0.0.1:8000',
          changeOrigin: false
        }
      }
    },
    test: {
      include: ['src/**/*.test.{ts,tsx}'],
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.ts',
      css: true
    }
  };
});
