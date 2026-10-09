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

export type OrganizationContext = {
  configured: boolean
  id?: number
  name: string
  industry: string
  description: string
  objectives: string[]
  constraints: string[]
  status?: string
  updated_at?: string
}

export type SupplyChainNode = {
  id: number
  chain_id: number
  key: string
  name: string
  stage_type: string
  owner_role: string
  position: { x: number; y: number }
  status: 'healthy' | 'at_risk' | 'critical' | 'stale' | 'disputed' | string
  metadata: Record<string, unknown>
  active: boolean
  verified_at: string | null
  verified_by: number | null
  pending_actions?: number
  updated_at: string
}

export type SupplyChainEdge = {
  id: number
  source: number
  target: number
  label: string
  status: string
}

export type ActionProposal = {
  id: number
  node_id: number
  node_name?: string
  title: string
  reason: string
  owner_role: string
  urgency: string
  expected_impact: string
  due_at: string | null
  status: string
  decision_note: string | null
  created_at: string
}

export type Evidence = {
  id: number
  node_id: number
  source_type: string
  event_type: string
  summary: string
  payload: Record<string, unknown>
  confidence: number
  status: string
  conflict_key: string | null
  occurred_at: string
}

export type NodeInspector = {
  node: SupplyChainNode
  evidence: Evidence[]
  guidance: {
    id: number
    provider: string
    status_summary: string
    rationale: string
    evidence_ids: number[]
    confidence: number
    no_action_required: boolean
    next_check_at: string
    stale: boolean
    actions: ActionProposal[]
  }
}

export type SupplyChainSummary = {
  id: number
  key: string
  name: string
  description: string
  status: 'active' | 'archived' | string
  created_at: string
  updated_at: string
  node_count: number
  archived_node_count: number
  status_counts: Record<string, number>
  worst_status: string
  pending_actions: number
  updated_node_at: string
}

export type SupplyChain = {
  chain: SupplyChainSummary | null
  organization: OrganizationContext
  nodes: SupplyChainNode[]
  edges: SupplyChainEdge[]
  updated_at: string
}

export type Permissions = {
  role: string
  permissions: string[]
}

export type NodeInput = {
  key: string
  name: string
  stage_type: string
  owner_role: string
  position_x?: number | null
  position_y?: number | null
  metadata?: Record<string, unknown>
}

export type OperatingRecord = Record<string, unknown> & { id: number }

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

export function getSupplyChain(token: string) {
  return request<SupplyChain>('/supply-chain', token)
}

export function getPermissions(token: string) {
  return request<Permissions>('/auth/permissions', token)
}

export function getNodeTemplates(token: string) {
  return request<OperatingRecord[]>('/node-templates', token)
}

export function getWorkflows(token: string) {
  return request<OperatingRecord[]>('/workflows', token)
}

export function getOperationalTasks(token: string) {
  return request<OperatingRecord[]>('/operational-tasks', token)
}

export function updateOperationalTask(token: string, id: number, input: Record<string, unknown>) {
  return request<OperatingRecord>(`/operational-tasks/${id}`, token, { method: 'PATCH', body: JSON.stringify(input) })
}

export function getInventoryLots(token: string) {
  return request<OperatingRecord[]>('/inventory/lots', token)
}

export function getPurchaseOrders(token: string) {
  return request<OperatingRecord[]>('/purchase-orders', token)
}

export function getShipments(token: string) {
  return request<OperatingRecord[]>('/shipments', token)
}

export function getQualityInspections(token: string) {
  return request<OperatingRecord[]>('/quality/inspections', token)
}

export function getRisks(token: string) {
  return request<OperatingRecord[]>('/risks', token)
}

export function getControlTowerExceptions(token: string) {
  return request<OperatingRecord[]>('/control-tower/exceptions', token)
}

export function listSupplyChains(token: string) {
  return request<{ chains: SupplyChainSummary[]; default_chain_id: number | null }>('/supply-chains', token)
}

export function getChainGraph(token: string, chainId: number) {
  return request<SupplyChain>(`/supply-chains/${chainId}`, token)
}

export function createSupplyChain(token: string, input: { key: string; name: string; description?: string }) {
  return request<SupplyChainSummary>('/supply-chains', token, { method: 'POST', body: JSON.stringify(input) })
}

export function updateSupplyChain(token: string, chainId: number, input: { key?: string; name?: string; description?: string }) {
  return request<SupplyChainSummary>(`/supply-chains/${chainId}`, token, { method: 'PUT', body: JSON.stringify(input) })
}

export function archiveSupplyChain(token: string, chainId: number) {
  return request<SupplyChainSummary>(`/supply-chains/${chainId}/archive`, token, { method: 'POST' })
}

export function restoreSupplyChain(token: string, chainId: number) {
  return request<SupplyChainSummary>(`/supply-chains/${chainId}/restore`, token, { method: 'POST' })
}

export function createNode(token: string, chainId: number, input: NodeInput) {
  return request<SupplyChainNode>(`/supply-chains/${chainId}/nodes`, token, { method: 'POST', body: JSON.stringify(input) })
}

export function updateNode(token: string, nodeId: number, input: Partial<NodeInput>) {
  return request<SupplyChainNode>(`/nodes/${nodeId}`, token, { method: 'PUT', body: JSON.stringify(input) })
}

export function deactivateNode(token: string, nodeId: number) {
  return request<SupplyChainNode>(`/nodes/${nodeId}`, token, { method: 'DELETE' })
}

export function activateNode(token: string, nodeId: number) {
  return request<SupplyChainNode>(`/nodes/${nodeId}/activate`, token, { method: 'POST' })
}

export function createEdge(token: string, chainId: number, input: { source_node_id: number; target_node_id: number; label?: string }) {
  return request<SupplyChainEdge>(`/supply-chains/${chainId}/edges`, token, { method: 'POST', body: JSON.stringify(input) })
}

export function updateEdge(token: string, edgeId: number, input: { label?: string; source_node_id?: number; target_node_id?: number }) {
  return request<SupplyChainEdge>(`/edges/${edgeId}`, token, { method: 'PUT', body: JSON.stringify(input) })
}

export function deleteEdge(token: string, edgeId: number) {
  return request<{ status: string }>(`/edges/${edgeId}`, token, { method: 'DELETE' })
}

export function verifyNode(token: string, nodeId: number, note: string) {
  return request<SupplyChainNode>(`/nodes/${nodeId}/verify`, token, { method: 'POST', body: JSON.stringify({ note }) })
}

export function escalateAction(token: string, actionId: number, note: string) {
  return request<ActionProposal>(`/actions/${actionId}/escalate`, token, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

export function getNodeInspector(token: string, nodeId: number) {
  return request<NodeInspector>(`/nodes/${nodeId}/inspector`, token)
}

export function refreshGuidance(token: string, nodeId: number) {
  return request<NodeInspector['guidance']>(`/nodes/${nodeId}/guidance/refresh`, token, { method: 'POST' })
}

export function getActions(token: string) {
  return request<ActionProposal[]>('/actions', token)
}

export function decideAction(token: string, actionId: number, decision: 'approved' | 'rejected') {
  return request<ActionProposal>(`/actions/${actionId}/decision`, token, {
    method: 'POST',
    body: JSON.stringify({ decision, expected_status: 'pending', note: 'Reviewed in control tower' }),
  })
}

export function addManualEvent(token: string, node: SupplyChainNode, input: { event_type: string; summary: string; conflict_key?: string }) {
  return request<Evidence>(`/nodes/${node.id}/manual-events`, token, {
    method: 'POST',
    body: JSON.stringify({ node_key: node.key, ...input, payload: { entered_in: 'control_tower' }, confidence: 0.8 }),
  })
}

export function updateOrganization(token: string, context: Omit<OrganizationContext, 'configured' | 'id' | 'status' | 'updated_at'>) {
  return request<OrganizationContext>('/organization/context', token, { method: 'PUT', body: JSON.stringify(context) })
}

export function updateUserContext(token: string, context: { owned_stages: string[]; timezone_name: string }) {
  return request('/users/me/context', token, {
    method: 'PUT',
    body: JSON.stringify({ ...context, decision_limits: { material_actions_require_approval: true }, escalation_preferences: { severity: 'high' } }),
  })
}
