import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'on-first-retry' },
  webServer: [
    { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: true },
    { command: 'cd ../backend && "C:/Users/Arihant Gupta/Desktop/infosec_project/.venv313/Scripts/python.exe" -m uvicorn app.main:app --port 8000', url: 'http://127.0.0.1:8000/health', reuseExistingServer: true },
  ],
})

