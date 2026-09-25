import react from '@vitejs/plugin-react';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
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
  const projectRoot = fileURLToPath(new URL('..', import.meta.url));
  const packageMetadata = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version?: unknown };
  const readGit = (...args: string[]) => {
    try {
      return execFileSync('git', args, { cwd: projectRoot, encoding: 'utf8' }).trim();
    } catch {
      return '';
    }
  };
  const sourceRevision = env.VITE_SOURCE_REVISION?.trim() || readGit('rev-parse', '--verify', 'HEAD');
  if (!/^[a-f0-9]{40}$/i.test(sourceRevision)) {
    throw new Error('Set VITE_SOURCE_REVISION to a full Git commit SHA to build the research application.');
  }
  const gitDirty = readGit('status', '--porcelain', '--untracked-files=normal').length > 0;
  const sourceTreeDirty = gitDirty || env.VITE_SOURCE_TREE_DIRTY?.trim().toLowerCase() === 'true';

  return {
    define: {
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(packageMetadata.version ?? 'unknown'),
      'import.meta.env.VITE_SOURCE_REVISION': JSON.stringify(sourceRevision),
      'import.meta.env.VITE_SOURCE_TREE_DIRTY': JSON.stringify(String(sourceTreeDirty))
    },
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
