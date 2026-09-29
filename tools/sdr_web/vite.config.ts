import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

// The bundle is written into the Python package so `./sdr gui` serves it.
// `npm run dev` proxies the WebSocket to a running `./sdr gui --no-browser`.
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: '../sdr_cli/web/static', emptyOutDir: true },
  server: { proxy: { '/ws': { target: 'ws://127.0.0.1:8080', ws: true } } },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
