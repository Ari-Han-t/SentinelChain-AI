import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import EntityManagement from '../src/EntityManagement'

const supplier = { id: 1, kind: 'suppliers', data: { name: 'Nova Components', reliability: .96, average_lead_time: 7, defect_rate: .01, price_variance: .04 }, governance: { owner_id: null, stage_id: null, warehouse_id: null, risk_level: 'low', minimum_clearance: 1 }, active: true, version: 1 }
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function mount(canManage = true) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><EntityManagement token="token" canManage={canManage}/></QueryClientProvider>)
}
function mockFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (data: unknown) => ({ ok: true, json: async () => data })
    if (url.includes('/entities/users')) return ok([])
    if (url.includes('/supply-chains')) return ok({ chains: [] })
    if (url.includes('/entities/warehouses')) return ok([])
    if (url.includes('/state')) return ok({ ...supplier, active: false, version: 2 })
    if (init?.method === 'POST') return ok({ ...supplier, data: JSON.parse(String(init.body)).data })
    if (url.endsWith('/entities/suppliers/1')) return ok({ ...supplier, related: {}, audit: [] })
    return ok([supplier])
  })
}
it('searches and filters records and loads functional details', async () => {
  const fetch = mockFetch(); vi.stubGlobal('fetch', fetch); mount()
  await screen.findByText('Nova Components')
  fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'Nova' } })
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('q=Nova'))).toBe(true))
  fireEvent.click(await screen.findByRole('button', { name: 'View Nova Components' }))
  expect(await screen.findByRole('button', { name: 'Edit entity' })).toBeInTheDocument()
})
it('saves validated create form with governance and audit reason', async () => {
  const fetch = mockFetch(); vi.stubGlobal('fetch', fetch); mount()
  fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
  fireEvent.change(screen.getByLabelText('Supplier name'), { target: { value: 'New supplier' } })
  fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Approved onboarding' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save entity' }))
  expect(await screen.findByText('Entity saved and change recorded in the audit trail.')).toBeInTheDocument()
  const call = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  const body = JSON.parse(String(call[1]?.body))
  expect(body.data.name).toBe('New supplier')
  expect(body.governance.minimum_clearance).toBe(1)
  expect(body.reason).toBe('Approved onboarding')
})
it('requires a reason and confirmation before deactivation', async () => {
  const fetch = mockFetch(); vi.stubGlobal('fetch', fetch); mount()
  fireEvent.click(await screen.findByRole('button', { name: 'View Nova Components' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate entity' }))
  expect(fetch.mock.calls.some(([url]) => url.includes('/state'))).toBe(false)
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Contract ended' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm deactivation' }))
  expect(await screen.findByText('Entity deactivated; history preserved.')).toBeInTheDocument()
})
it('provides read-only views without mutation controls', async () => {
  vi.stubGlobal('fetch', mockFetch()); mount(false)
  expect(screen.queryByRole('button', { name: 'Create entity' })).toBeNull()
  fireEvent.click(await screen.findByRole('button', { name: 'View Nova Components' }))
  await screen.findByRole('region', { name: 'Entity details' })
  expect(await screen.findByRole('heading', { name: 'Ownership and security' })).toBeInTheDocument()
  expect(screen.getByText('Assigned owner', { exact: true })).toBeInTheDocument()
  expect(screen.getByText('Linked stage', { exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Edit entity' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Deactivate entity' })).toBeNull()
})
it('displays actionable validation messages from the API', async () => {
  const fetch = mockFetch()
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? Promise.resolve({ ok: false, json: async () => ({ detail: [{ loc: ['data', 'name'], msg: 'Name already exists' }] }) }) : fetch(url, init)))
  mount(); fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
  fireEvent.change(screen.getByLabelText('Supplier name'), { target: { value: 'Existing' } })
  fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Create supplier' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save entity' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('data.name: Name already exists')
})
