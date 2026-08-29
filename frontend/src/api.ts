export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type User = {
  id: number
  email: string
  display_name: string
  role: string
}

export type DashboardData = {
  synthetic: boolean
  kpis: {
    total_skus: number
    low_stock_skus: number
    open_security_alerts: number
    pending_approvals: number
  }
  demand_series: Array<{ date: string; quantity: number }>
  products: Array<{ sku: string; name: string; current_stock: number; lead_time_days: number; health: string }>
  alerts: Array<{ id: number; category: string; severity: string; title: string; detail: string; created_at: string }>
  recommendations: Recommendation[]
}

export type Recommendation = {
  id: number
  sku: string
  product_name: string
  reorder_point: number
  safety_stock: number
  eoq: number
  recommended_quantity: number
  supplier_risk: number
  status: string
  created_at: string
}

async function request<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(payload.detail ?? 'Request failed')
  }
  return response.json()
}

export function login(email: string, password: string) {
  return request<{ access_token: string; user: User }>('/auth/login', undefined, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function getDashboard(token: string) {
  return request<DashboardData>('/dashboard', token)
}

export function getAlerts(token: string) {
  return request<DashboardData['alerts']>('/alerts', token)
}

export function getSuppliers(token: string) {
  return request<Array<{ id: number; name: string; reliability: number; average_lead_time: number; defect_rate: number; price_variance: number; risk_score: number }>>('/suppliers', token)
}

export function getAudit(token: string) {
  return request<{ valid: boolean; broken_at: number | null; events: Array<Record<string, unknown>> }>('/audit', token)
}

export function trainForecast(token: string, sku: string) {
  return request<Record<string, unknown>>(`/forecasts/${sku}/train`, token, { method: 'POST' })
}

export function generateRecommendation(token: string, sku: string) {
  return request<Recommendation>(`/recommendations/generate/${sku}`, token, { method: 'POST' })
}

export function decideRecommendation(token: string, id: number, decision: 'approved' | 'rejected') {
  return request<Recommendation>(`/recommendations/${id}/decision`, token, {
    method: 'POST',
    body: JSON.stringify({ decision, expected_status: 'pending', note: 'Reviewed in control tower' }),
  })
}

export function runAttack(token: string, attack_type: string, sku = 'SKU-001') {
  return request<{ attack_type: string; detected: boolean; quarantined: boolean; unsafe_decision: { purchase_quantity: number }; protected_decision: { purchase_quantity: number }; message: string }>('/demo/attacks', token, {
    method: 'POST',
    body: JSON.stringify({ attack_type, sku }),
  })
}

