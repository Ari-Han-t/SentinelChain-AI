import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'

afterEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
})

function renderApp() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><App /></QueryClientProvider>)
}

describe('SentinelChain application', () => {
  it('authenticates and shows verified dashboard data', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: 'token', user: { id: 1, email: 'admin@sentinelchain.local', display_name: 'Ari Admin', role: 'administrator' } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ synthetic: true, kpis: { total_skus: 3, low_stock_skus: 1, open_security_alerts: 0, pending_approvals: 0 }, demand_series: [], products: [], alerts: [], recommendations: [] }) }))
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /enter control tower/i }))
    expect(await screen.findByText('Supply chain overview')).toBeInTheDocument()
    expect(screen.getByText('Data chain verified')).toBeInTheDocument()
  })

  it('shows an authentication error without losing the form', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: 'Invalid email or password' }) }))
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /enter control tower/i }))
    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveValue('admin@sentinelchain.local'))
  })
})
