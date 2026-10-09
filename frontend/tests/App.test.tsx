import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'

afterEach(() => {
  cleanup()
  sessionStorage.clear()
  localStorage.clear()
  vi.restoreAllMocks()
})

function renderApp() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><App /></QueryClientProvider>)
}

const ADMIN_PERMISSIONS = ['action.decide', 'action.escalate', 'audit.read', 'chain.manage', 'demo.attack', 'edge.manage', 'evidence.submit', 'forecast.manage', 'guidance.refresh', 'node.manage', 'node.verify', 'org.manage', 'recommendation.generate']
const ANALYST_PERMISSIONS = ['evidence.submit', 'forecast.manage', 'guidance.refresh', 'recommendation.generate']

const graphPayload = {
  chain: { id: 1, key: 'sentinel-industrial-demo', name: 'Sentinel Industrial Demo', description: '', status: 'active', node_count: 0, archived_node_count: 0, status_counts: {}, worst_status: 'empty', pending_actions: 0 },
  organization: { configured: true, name: 'Sentinel Industrial Demo', industry: 'Industrial components', description: '', objectives: [], constraints: [] },
  nodes: [],
  edges: [],
  updated_at: new Date().toISOString(),
}

function mockApi(role: string, permissions: string[]) {
  return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const respond = (payload: unknown) => Promise.resolve({ ok: true, json: async () => payload })
    if (String(url).includes('/auth/login')) {
      return respond({ access_token: 'token', user: { id: 1, email: `${role}@sentinelchain.local`, display_name: 'Test User', role } })
    }
    if (String(url).includes('/auth/permissions')) return respond({ role, permissions })
    if (init?.method === 'POST' && String(url).endsWith('/supply-chains')) {
      return respond({ id: 9, key: 'created-chain', name: 'Created chain', description: '', status: 'active', node_count: 0, archived_node_count: 0, status_counts: {}, worst_status: 'empty', pending_actions: 0 })
    }
    if (String(url).endsWith('/supply-chains')) return respond({ chains: [graphPayload.chain], default_chain_id: 1 })
    if (String(url).includes('/supply-chains/1') || String(url).endsWith('/supply-chain')) return respond(graphPayload)
    return Promise.resolve({ ok: false, json: async () => ({ detail: `Unhandled ${String(url)}` }) })
  })
}

describe('SentinelChain application', () => {
  it('authenticates and shows the shared supply-chain workspace', async () => {
    vi.stubGlobal('fetch', mockApi('administrator', ADMIN_PERMISSIONS))
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /enter shared workspace/i }))
    expect(await screen.findByText('Sentinel Industrial Demo')).toBeInTheDocument()
    expect(screen.getByText('Every handoff monitored. Every recommendation tied to evidence.')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /supply chains/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(await screen.findByRole('combobox', { name: /switch supply chain/i })).toBeInTheDocument()
  })

  it('hides administration navigation from non-admin roles', async () => {
    vi.stubGlobal('fetch', mockApi('inventory_analyst', ANALYST_PERMISSIONS))
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /enter shared workspace/i }))
    expect(await screen.findByText('Sentinel Industrial Demo')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /action queue/i })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
    expect(screen.queryByRole('button', { name: /supply chains/i })).toBeNull()
    expect(screen.getByText('Inventory analyst')).toBeInTheDocument()
  })

  it('shows an authentication error without losing the form', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: 'Invalid email or password' }) }))
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /enter shared workspace/i }))
    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveValue('admin@sentinelchain.local'))
  })
})
