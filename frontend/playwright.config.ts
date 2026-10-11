import { defineConfig } from '@playwright/test'

const python = process.env.E2E_PYTHON ?? (process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
const webPort = process.env.E2E_WEB_PORT ?? '5175'
const apiPort = process.env.E2E_API_PORT ?? '8101'
export default defineConfig({
  testDir: './tests/e2e',
  metadata: { apiURL: `http://127.0.0.1:${apiPort}` },
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${webPort}`, trace: 'on-first-retry', ...(process.env.E2E_CHROME ? { channel: 'chrome' } : {}) },
  webServer: [
    { command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`, url: `http://127.0.0.1:${webPort}`, reuseExistingServer: false, env: { VITE_API_URL: `http://127.0.0.1:${apiPort}` } },
    { command: `cd ../backend && ${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`, url: `http://127.0.0.1:${apiPort}/health`, reuseExistingServer: false, env: { DATABASE_URL: 'sqlite:///./e2e-sentinelchain.db', AI_PROVIDER: 'deterministic', AZURE_AI_FOUNDRY_ENABLED: 'false', SEED_DEMO_DATA: 'true', DEMO_MODE: 'true', ENVIRONMENT: 'development', CORS_ORIGINS: `http://127.0.0.1:${webPort}`, RATE_LIMIT_PER_MINUTE: '10000' } },
  ],
})
