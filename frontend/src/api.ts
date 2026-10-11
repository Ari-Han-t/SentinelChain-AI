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
  step: StepSpecification
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

export type StepSpecification = {
    name: string
    key: string
    stage_type: string
    entities: {
      people: Array<{ id: number; display_name: string; role: string; clearance_level: number; permissions: string[] }>
      items: Array<{ name: string; quantity: number; access: string[] }>
    }
    actions: Array<{ key: string; label: string; permission: string; minimum_clearance: number; allowed: boolean; role: string; role_label: string }>
    security: { policy_source: string; metadata_can_describe: boolean; authorization_enforced_by: string }
}

export type ClearanceMatrix = {
    clearance_levels: Array<{ role: string; label: string; level: number; permissions: string[]; actions: Array<{ key: string; label: string; permission: string; minimum_clearance: number; allowed: boolean }> }>
    items_by_stage: Record<string, Array<{ name: string; quantity: number; access: string[] }>>
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
    const detail = payload.detail
    throw new Error(Array.isArray(detail) ? detail.map((item: { loc?: Array<string | number>; msg?: string }) => `${item.loc?.join('.') ?? 'Input'}: ${item.msg ?? 'Invalid value'}`).join('; ') : typeof detail === 'string' ? detail : 'Request failed')
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

export function getClearanceMatrix(token: string) {
  return request<ClearanceMatrix>('/security/clearance-matrix', token)
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

export type EntityKind = 'suppliers' | 'warehouses' | 'products' | 'inventory' | 'purchase-orders' | 'shipments'
export type EntityGovernance = { owner_id: number | null; stage_id: number | null; warehouse_id: number | null; risk_level: string; minimum_clearance: number }
export type ManagedEntity = { id: number; kind: EntityKind; data: Record<string, unknown>; governance: EntityGovernance; governance_labels?: Record<string, string>; active: boolean; version: number; related?: Record<string, Array<Record<string, unknown>>>; audit?: Array<Record<string, unknown>> }
export const listEntities = (token: string, kind: EntityKind, filters = '') => request<ManagedEntity[]>(`/entities/${kind}${filters}`, token)
export const getEntity = (token: string, kind: EntityKind, id: number) => request<ManagedEntity>(`/entities/${kind}/${id}`, token)
export const getEntityUsers = (token: string) => request<Array<{ id: number; display_name: string; role: string }>>('/entities/users', token)
export const saveEntity = (token: string, kind: EntityKind, body: { data: Record<string, unknown>; governance: EntityGovernance; reason: string; expected_version?: number }, id?: number) => request<ManagedEntity>(`/entities/${kind}${id ? `/${id}` : ''}`, token, { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) })
export const setEntityState = (token: string, entity: ManagedEntity, reason: string) => request<ManagedEntity>(`/entities/${entity.kind}/${entity.id}/state`, token, { method: 'POST', body: JSON.stringify({ active: !entity.active, expected_version: entity.version, reason }) })

export type PolicyRule = {
  key: string; operation: string; priority: number; active: boolean; minimum_clearance: number
  deny_at_risk: string; max_quantity_delta: number | null; effective_from: string | null; effective_until: string | null
}
export type PolicyConfiguration = {
  role_permissions: Record<string, string[]>; entity_clearance: Record<string, number>; operation_clearance: Record<string, number>
  approval_quantity_threshold: number; approval_risk_threshold: number; rules: PolicyRule[]
}
export type PolicyRevision = {
  id: number; configuration: PolicyConfiguration; status: string; base_generation: number; digest: string
  created_by: number | null; created_at: string; reason: string; published_by: number | null; published_at: string | null
}
export type PolicyOverview = {
  generation: number; active_revision_id: number; configuration: PolicyConfiguration; permission_ceiling: Record<string, string[]>
  clearance_levels: Record<string, number>; revisions: PolicyRevision[]; users: Array<{id: number; display_name: string; role: string}>
}
export const getPolicies = (token: string) => request<PolicyOverview>('/security/policies', token)
export const draftPolicy = (token: string, configuration: PolicyConfiguration, expected_generation: number, reason: string) => request<PolicyRevision>('/security/policies/drafts', token, {method:'POST', body:JSON.stringify({configuration,expected_generation,reason})})
export const activatePolicy = (token: string, id: number, action: 'publish'|'revert', expected_generation: number, reason: string) => request<{generation:number;active_revision_id:number}>(`/security/policies/${id}/${action}`, token, {method:'POST',body:JSON.stringify({expected_generation,reason})})
export const assignPolicyRole = (token: string, id: number, role: string, expected_role: string, reason: string) => request(`/security/policies/users/${id}/role`, token, {method:'POST',body:JSON.stringify({role,expected_role,reason})})

export type IntegrationConnection = {
  id:number; name:string; system:string; mode:'mock'|'live'; profile:string|null; enabled:boolean; mock_scenario:string; stale_after_seconds:number
  version:number; health:string; checked_at:string|null; synced_at:string|null; retry_at:string|null; created_at:string; stale:boolean; busy:boolean
  provenance:'mock'|'live'; data_state:string; has_more:boolean
}
export type IntegrationRun = {
  id:string; connection_id:number; operation:string; status:string; attempts:number; accepted:number; duplicates:number; ignored:number
  error_code:string|null; error_detail:string|null; reason:string; requested_by:number; started_at:string; finished_at:string|null; duplicate_request:boolean
}
export type IntegrationRecord = {
  id:number; connection_id:number; resource:string; external_id:string; source_version:number; provenance:'mock'|'synchronized'; occurred_at:string; received_at:string
  run_id:string; entity_id:number|null; applied_version:number|null; applied_at:string|null; data:Record<string,unknown>; stale:boolean; review_status:string; entity_version:number|null
}
export type IntegrationCreate = {name:string;system:string;mode:'mock'|'live';profile:string|null;enabled:boolean;mock_scenario:string;stale_after_seconds:number;reason:string}
export const getIntegrations = (token:string) => request<{connections:IntegrationConnection[];total:number}>('/integrations',token)
export const getIntegrationProfiles = (token:string) => request<{profiles:Array<{name:string;system:string}>;mock_allowed:boolean}>('/integrations/profiles',token)
export const createIntegration = (token:string,body:IntegrationCreate) => request<IntegrationConnection>('/integrations',token,{method:'POST',body:JSON.stringify(body)})
export const setIntegrationState = (token:string,id:number,enabled:boolean,expected_version:number,reason:string) => request<IntegrationConnection>(`/integrations/${id}/state`,token,{method:'POST',body:JSON.stringify({enabled,expected_version,reason})})
export const runIntegration = (token:string,id:number,action:'check'|'sync',idempotency_key:string,reason:string) => request<IntegrationRun>(`/integrations/${id}/${action}`,token,{method:'POST',body:JSON.stringify({idempotency_key,reason})})
export const getIntegrationRuns = (token:string,id:number) => request<IntegrationRun[]>(`/integrations/${id}/runs`,token)
export const getIntegrationRecords = (token:string,id:number,q:string,review_status:string,offset=0) => request<{records:IntegrationRecord[];total:number}>(`/integrations/${id}/records?${new URLSearchParams({q,review_status,offset:String(offset)})}`,token)
export const getIntegrationRecord = (token:string,id:number,recordId:number) => request<IntegrationRecord>(`/integrations/${id}/records/${recordId}`,token)
export const applyIntegrationRecord = (token:string,id:number,recordId:number,body:{expected_source_version:number;target_entity_id:number|null;expected_entity_version:number|null;parent_entity_id:number|null;reason:string}) => request<{record_id:number;entity_id:number;duplicate_request:boolean}>(`/integrations/${id}/records/${recordId}/apply`,token,{method:'POST',body:JSON.stringify(body)})

export type HistoryRecord={kind:'stock'|'stage';source_id:number;created_at:string;status:string;decided_by:{id:number;name:string}|null;decision_note:string|null;version:number;implementation_status:string;outcome:string;feedback:string;explanation:{summary:string;affected:{kind:string;id:number;name:string};category:string;severity:string;snapshot_state:string;evidence:Array<{kind:string;id:number;summary:string;data?:Record<string,unknown>;source?:string;status?:string;occurred_at?:string}>;reasoning:string;consequences:string[];mitigation:string[];confidence:number|null;confidence_basis:string;missing_information:string[];provider?:string;risk_values:Record<string,unknown>};history?:Array<{id:number;event_type:string;actor_id:number|null;actor_name:string;created_at:string;detail:Record<string,unknown>;audit_id:number}>;risk_history?:Array<Record<string,unknown>>}
export const getRecommendationHistory=(token:string,params:string)=>request<{records:HistoryRecord[];total:number}>(`/recommendation-history?${params}`,token)
export const getHistoryDetail=(token:string,kind:string,id:number)=>request<HistoryRecord>(`/recommendation-history/${kind}/${id}`,token)
export const decideHistory=(token:string,kind:string,id:number,body:{decision:string;expected_status:string;note:string})=>request<HistoryRecord>(`/recommendation-history/${kind}/${id}/decision`,token,{method:'POST',body:JSON.stringify(body)})
export const reportHistory=(token:string,kind:string,id:number,body:{expected_version:number;implementation_status:string;outcome:string;feedback:string;reason:string})=>request<HistoryRecord>(`/recommendation-history/${kind}/${id}/feedback`,token,{method:'POST',body:JSON.stringify(body)})
export type Incident={id:number;category:string;severity:string;title:string;detail:string;entity_kind:string|null;entity_id:number|null;status:string;assigned_role:string;assigned_user_id:number|null;assigned_user_name:string|null;escalation_role:string;escalation_at:string;due_at:string;escalation_level:number;occurrence_count:number;acknowledged_by:number|null;acknowledged_at:string|null;resolved_by:number|null;resolved_at:string|null;resolution_note:string|null;version:number;created_at:string;last_occurred_at:string;overdue:boolean;deliveries?:Array<{id:number;user_id:number;level:number;channel:string;status:string;attempts:number;error_code:string|null;read_at:string|null;created_at:string}>;history?:Array<{id:number;event_type:string;actor_id:number|null;actor_name:string;created_at:string;detail:Record<string,unknown>}>}
export type Notification={id:number;read_at:string|null;level:number;created_at:string;incident:Incident}
export type NotificationRule={id:number;category:string;enabled:boolean;minimum_severity:string;assigned_role:string;assigned_user_id:number|null;escalation_role:string;escalation_minutes:number;remediation_minutes:number;quantity_threshold?:number;version:number}
export const getNotifications=(token:string,unread=false,offset=0)=>request<{notifications:Notification[];total:number;unread_count:number}>(`/notifications?unread=${unread}&offset=${offset}`,token)
export const readNotification=(token:string,id:number,read:boolean)=>request<{id:number;read_at:string|null}>(`/notifications/${id}/read`,token,{method:'POST',body:JSON.stringify({read})})
export const getIncidents=(token:string,params:string)=>request<{incidents:Incident[];total:number}>(`/incidents?${params}`,token)
export const getIncident=(token:string,id:number)=>request<Incident>(`/incidents/${id}`,token)
export const changeIncident=(token:string,id:number,body:{expected_version:number;action:string;reason:string;assigned_role?:string;assigned_user_id?:number|null})=>request<Incident>(`/incidents/${id}/transition`,token,{method:'POST',body:JSON.stringify(body)})
export const getNotificationRules=(token:string)=>request<{rules:NotificationRule[];users:Array<{id:number;name:string;role:string}>;channels:Array<{name:string;configured:boolean}>}>('/notification-rules',token)
export const saveNotificationRule=(token:string,category:string,body:Omit<NotificationRule,'id'|'category'|'version'>&{expected_version:number;reason:string})=>request<NotificationRule>(`/notification-rules/${category}`,token,{method:'PUT',body:JSON.stringify(body)})
export const reconcileNotifications=(token:string)=>request<{status:string;checked_at:string}>('/notifications/reconcile',token,{method:'POST'})

export type SecurityAudit = {id:number;sequence:number;event_type:string;actor_id:number|null;actor_name:string;identity_type:string;entity:{kind:string;id:number}|null;created_at:string;authorization_decision:string;policy_revision_id:number|null;request_id:string|null;outcome:string;reason:string|null;severity:string;related:Record<string,number>;payload:Record<string,unknown>;metadata_state:string;event_hash:string}
export type Simulation = {id:number;scenario:string;actor_id:number;policy_revision_id:number;audit_id:number;created_at:string;report:{status:string;detected:boolean;blocked:boolean;isolation:string;policies_evaluated?:string[];expected_outcome:string;actual_outcome:string;operational_state_unchanged:boolean;initial_conditions:Record<string,unknown>;final_conditions:Record<string,unknown>;simulated_actions:Array<Record<string,unknown>>;audit_events:Array<Record<string,unknown>>}}
export const getSecurityAudit=(token:string,params:string)=>request<{records:SecurityAudit[];total:number;valid:boolean;broken_at:number|null;users:Array<{id:number;name:string}>}>(`/security/audit?${params}`,token)
export const getSimulations=(token:string,offset=0)=>request<{records:Simulation[];total:number;enabled:boolean;scenarios:string[]}>(`/security/simulations?offset=${offset}`,token)
export const runSimulation=(token:string,scenario:string,reason:string)=>request<Simulation>('/security/simulations',token,{method:'POST',body:JSON.stringify({scenario,reason})})
export const getSecurityOverview=(token:string)=>request<{audit_integrity:{valid:boolean;broken_at:number|null};unresolved_total:number;unresolved_incidents:Array<{id:number;title:string;severity:string;status:string;owner:string;due_at:string;escalated:boolean}>;recent_simulations:Array<{id:number;scenario:string;status:string;created_at:string}>;integration_health:Array<{id:number;name:string;mode:string;enabled:boolean;synced_at:string|null;health:string}>;environment:{name:string;simulations_enabled:boolean;demo_data:boolean}}>('/security/overview',token)
