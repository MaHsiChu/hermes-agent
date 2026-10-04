import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'static-shell-worker',
      generateBundle(_options, bundle) {
        const assets = Object.keys(bundle)
          .filter(path => /\.(js|css)$/.test(path))
          .map(path => `/${path}`)
        const version = createHash('sha256').update(assets.join('|')).digest('hex').slice(0, 12)
        const source = readFileSync(new URL('./public/sw.js', import.meta.url), 'utf8')
          .replace('__BUILD__', version)
          .replace('/* BUILD_ASSETS */ []', JSON.stringify(assets))
        this.emitFile({ type: 'asset', fileName: 'sw.js', source })
      }
    }
  ],
  server: {
    port: 5174,
    strictPort: true,
    proxy: Object.fromEntries(
      ['/api/remote', '/auth'].map(path => [
        path,
        { target: process.env.RELAY_TARGET || 'http://127.0.0.1:8787', ws: true }
      ])
    )
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'], restoreMocks: true }
})
