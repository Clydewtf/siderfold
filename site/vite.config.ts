import react from '@vitejs/plugin-react';
import type { InlineConfig } from 'vitest';
import { defineConfig } from 'vite';

declare module 'vite' {
  interface UserConfig {
    test?: InlineConfig;
  }
}

export default defineConfig({
  plugins: [react()],
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: true
  }
});
