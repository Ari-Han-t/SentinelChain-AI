import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  Boxes,
  Check,
  ChevronRight,
  ClipboardCheck,
  DatabaseZap,
  FileClock,
  Gauge,
  LogOut,
  PackageCheck,
  Radar,
  ShieldCheck,
  ShieldX,
  Sparkles,
  Truck,
  X,
} from 'lucide-react'
import { FormEvent, useState } from 'react'
import {
  DashboardData,
  User,
  decideRecommendation,
  generateRecommendation,
  getAlerts,
  getAudit,
  getDashboard,
  getSuppliers,
  login,
  runAttack,
  trainForecast,
} from './api'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type Session = { token: string; user: User }
type View = 'overview' | 'suppliers' | 'security' | 'approvals' | 'audit'

const roleLabel: Record<string, string> = {
  administrator: 'Administrator',
  inventory_analyst: 'Inventory Analyst',
  procurement_manager: 'Procurement Manager',
  auditor: 'Auditor',
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [email, setEmail] = useState('admin@sentinelchain.local')
  const [password, setPassword] = useState('demo1234')
  const mutation = useMutation({ mutationFn: () => login(email, password), onSuccess: (data) => onLogin({ token: data.access_token, user: data.user }) })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  return (
    <main className="login-shell">
      <section className="login-story">
        <div className="brand-mark"><ShieldCheck size={24} /><span>SentinelChain AI</span></div>
        <div>
          <span className="eyebrow">SECURE SUPPLY CHAIN INTELLIGENCE</span>
          <h1>Trust every signal.<br />Approve every action.</h1>
          <p>Forecast demand, isolate poisoned data, and protect procurement decisions with evidence that cannot be quietly rewritten.</p>
        </div>
        <div className="trust-strip">
          <span><span className="status-dot" /> HMAC verified imports</span>
          <span><span className="status-dot" /> Human-approved orders</span>
          <span><span className="status-dot" /> Hash-chained audit</span>
        </div>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div className="mobile-brand"><ShieldCheck size={22} /> SentinelChain AI</div>
          <p className="eyebrow">CONTROL TOWER ACCESS</p>
          <h2>Welcome back</h2>
          <p className="muted">Use a seeded role to explore the synthetic demo.</p>
          <label>Email<input aria-label="Email" value={email} onChange={(event) => setEmail(event.target.value)} type="email" /></label>
          <label>Password<input aria-label="Password" value={password} onChange={(event) => setPassword(event.target.value)} type="password" /></label>
          {mutation.error && <div className="error-banner">{mutation.error.message}</div>}
          <button className="primary-button" disabled={mutation.isPending}>{mutation.isPending ? 'Authenticating…' : 'Enter control tower'} <ChevronRight size={17} /></button>
          <div className="demo-note"><Sparkles size={16} /><span>Demo: all seeded accounts use <code>demo1234</code></span></div>
        </form>
      </section>
    </main>
  )
}

function KpiCard({ label, value, detail, icon: Icon, tone = 'cyan' }: { label: string; value: number | string; detail: string; icon: typeof Gauge; tone?: string }) {
  return <article className={`kpi-card tone-${tone}`}><div className="kpi-icon"><Icon size={19} /></div><div><p>{label}</p><strong>{value}</strong><small>{detail}</small></div></article>
}

function Overview({ data, token }: { data: DashboardData; token: string }) {
  const client = useQueryClient()
  const [message, setMessage] = useState('')
  const build = useMutation({
    mutationFn: async (sku: string) => {
      await trainForecast(token, sku)
      return generateRecommendation(token, sku)
    },
    onSuccess: (item) => {
      setMessage(`Recommendation #${item.id} generated for ${item.sku}.`)
      client.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  return <>
    <div className="page-heading"><div><p className="eyebrow">LIVE OPERATIONS</p><h1>Supply chain overview</h1><p>Verified operational data only. Every value below is synthetic.</p></div><span className="verified-pill"><ShieldCheck size={15} /> Data chain verified</span></div>
    <section className="kpi-grid">
      <KpiCard label="Tracked SKUs" value={data.kpis.total_skus} detail="Across synthetic catalog" icon={Boxes} />
      <KpiCard label="Stock watchlist" value={data.kpis.low_stock_skus} detail="Below lead-time threshold" icon={Gauge} tone="amber" />
      <KpiCard label="Security alerts" value={data.kpis.open_security_alerts} detail="Integrity and access" icon={ShieldX} tone="red" />
      <KpiCard label="Awaiting approval" value={data.kpis.pending_approvals} detail="No autonomous orders" icon={ClipboardCheck} tone="green" />
    </section>
    <section className="dashboard-grid">
      <article className="panel demand-panel">
        <div className="panel-header"><div><p className="eyebrow">30-DAY SIGNAL</p><h2>Aggregate demand</h2></div><span className="synthetic-tag">SYNTHETIC</span></div>
        <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data.demand_series}><defs><linearGradient id="demand" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#38d7e8" stopOpacity={0.4}/><stop offset="100%" stopColor="#38d7e8" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#173047" vertical={false}/><XAxis dataKey="date" hide/><YAxis stroke="#6d8499" tickLine={false} axisLine={false}/><Tooltip contentStyle={{ background: '#0d1b2a', border: '1px solid #20394f', borderRadius: 10 }}/><Area type="monotone" dataKey="quantity" stroke="#38d7e8" strokeWidth={2.5} fill="url(#demand)"/></AreaChart></ResponsiveContainer></div>
      </article>
      <article className="panel alert-panel">
        <div className="panel-header"><div><p className="eyebrow">ACTIVE SIGNALS</p><h2>Risk queue</h2></div><AlertTriangle size={19} className="amber" /></div>
        <div className="stack-list">{data.alerts.length ? data.alerts.map((alert) => <div className="alert-row" key={alert.id}><span className={`severity ${alert.severity}`} /><div><strong>{alert.title}</strong><p>{alert.detail}</p></div></div>) : <div className="empty">No open alerts</div>}</div>
      </article>
    </section>
    <article className="panel inventory-panel">
      <div className="panel-header"><div><p className="eyebrow">INVENTORY HEALTH</p><h2>Decision-ready products</h2></div>{message && <span className="success-note">{message}</span>}</div>
      <div className="table-wrap"><table><thead><tr><th>Product</th><th>On hand</th><th>Lead time</th><th>Health</th><th></th></tr></thead><tbody>{data.products.map((product) => <tr key={product.sku}><td><strong>{product.name}</strong><span>{product.sku}</span></td><td>{product.current_stock} units</td><td>{product.lead_time_days} days</td><td><span className={`health ${product.health}`}>{product.health}</span></td><td><button className="quiet-button" onClick={() => build.mutate(product.sku)} disabled={build.isPending}>{build.isPending ? 'Calculating…' : 'Forecast + recommend'}</button></td></tr>)}</tbody></table></div>
      {build.error && <div className="error-banner">{build.error.message}</div>}
    </article>
  </>
}

function Suppliers({ token }: { token: string }) {
  const query = useQuery({ queryKey: ['suppliers'], queryFn: () => getSuppliers(token) })
  return <><div className="page-heading"><div><p className="eyebrow">SUPPLIER INTELLIGENCE</p><h1>Risk scorecards</h1><p>Weighted from reliability, lead time, defects, and price variance.</p></div></div><section className="card-grid">{query.data?.map((supplier) => <article className="supplier-card" key={supplier.id}><div className="supplier-top"><div className="supplier-icon"><Truck /></div><span className={`risk-score ${supplier.risk_score > 35 ? 'high' : supplier.risk_score > 20 ? 'medium' : 'low'}`}>{supplier.risk_score}</span></div><h2>{supplier.name}</h2><p>Composite risk / 100</p><dl><div><dt>Reliability</dt><dd>{Math.round(supplier.reliability * 100)}%</dd></div><div><dt>Avg. lead time</dt><dd>{supplier.average_lead_time}d</dd></div><div><dt>Defect rate</dt><dd>{(supplier.defect_rate * 100).toFixed(1)}%</dd></div><div><dt>Price variance</dt><dd>{(supplier.price_variance * 100).toFixed(1)}%</dd></div></dl></article>)}</section></>
}

function SecurityLab({ token }: { token: string }) {
  const [result, setResult] = useState<Awaited<ReturnType<typeof runAttack>> | null>(null)
  const mutation = useMutation({ mutationFn: (type: string) => runAttack(token, type), onSuccess: setResult })
  const attacks = [
    ['demand_poisoning', 'Demand poisoning', 'Inject a 12,000-unit spike into a verified demand stream.'],
    ['inventory_manipulation', 'Stock manipulation', 'Attempt an impossible negative inventory adjustment.'],
    ['supplier_spoofing', 'Supplier spoofing', 'Present an unverified look-alike supplier identity.'],
  ]
  return <><div className="page-heading"><div><p className="eyebrow">ADMIN-ONLY SANDBOX</p><h1>Attack and recovery lab</h1><p>Run controlled attacks against synthetic data. Production mode disables this endpoint.</p></div><span className="danger-pill"><DatabaseZap size={15}/> Demo environment</span></div><section className="attack-grid">{attacks.map(([id, title, description]) => <button className="attack-card" key={id} onClick={() => mutation.mutate(id)} disabled={mutation.isPending}><Radar /><span><strong>{title}</strong><small>{description}</small></span><ChevronRight /></button>)}</section>{mutation.error && <div className="error-banner">{mutation.error.message}</div>}{result && <article className="comparison-panel"><div className="result-title"><ShieldCheck/><div><p className="eyebrow">ATTACK CONTAINED</p><h2>{result.message}</h2></div></div><div className="comparison-grid"><div className="unsafe"><span>Without controls</span><strong>{result.unsafe_decision.purchase_quantity.toLocaleString()} units</strong><p>Unsafe purchase from compromised input</p></div><div className="protected"><span>SentinelChain decision</span><strong>{result.protected_decision.purchase_quantity.toLocaleString()} units</strong><p>Last verified data remains in control</p></div></div></article>}</>
}

function Approvals({ data, token }: { data: DashboardData; token: string }) {
  const client = useQueryClient()
  const mutation = useMutation({ mutationFn: ({ id, decision }: { id: number; decision: 'approved' | 'rejected' }) => decideRecommendation(token, id, decision), onSuccess: () => client.invalidateQueries({ queryKey: ['dashboard'] }) })
  return <><div className="page-heading"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h1>Purchase approvals</h1><p>Recommendations explain their inputs and never create a real order automatically.</p></div></div><div className="approval-list">{data.recommendations.length ? data.recommendations.map((item) => <article className="approval-card" key={item.id}><div><span className={`health ${item.status}`}>{item.status}</span><h2>{item.product_name} <small>{item.sku}</small></h2><p>Order <strong>{item.recommended_quantity} units</strong> based on a {item.reorder_point.toFixed(0)} reorder point, {item.safety_stock.toFixed(0)} safety stock, EOQ {item.eoq.toFixed(0)}, and supplier risk {item.supplier_risk}/100.</p></div>{item.status === 'pending' && <div className="approval-actions"><button className="reject" onClick={() => mutation.mutate({ id: item.id, decision: 'rejected' })}><X size={16}/> Reject</button><button className="approve" onClick={() => mutation.mutate({ id: item.id, decision: 'approved' })}><Check size={16}/> Approve simulation</button></div>}</article>) : <div className="empty panel">Generate a recommendation from the overview first.</div>}</div></>
}

function Audit({ token }: { token: string }) {
  const query = useQuery({ queryKey: ['audit'], queryFn: () => getAudit(token) })
  return <><div className="page-heading"><div><p className="eyebrow">ACCOUNTABILITY</p><h1>Tamper-evident audit chain</h1><p>Each event includes the previous event hash; any edit breaks verification.</p></div>{query.data && <span className={query.data.valid ? 'verified-pill' : 'danger-pill'}>{query.data.valid ? <ShieldCheck size={15}/> : <ShieldX size={15}/>} {query.data.valid ? 'Chain intact' : `Broken at #${query.data.broken_at}`}</span>}</div><article className="panel audit-panel">{query.error && <div className="error-banner">{query.error.message}</div>}{query.data?.events.map((event) => <div className="audit-row" key={String(event.sequence)}><span className="audit-sequence">#{String(event.sequence).padStart(3, '0')}</span><div><strong>{String(event.event_type)}</strong><p>{new Date(String(event.created_at)).toLocaleString()} · actor {String(event.actor_id ?? 'system')}</p><code>{String(event.event_hash).slice(0, 20)}…</code></div></div>)}</article></>
}

function Shell({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [view, setView] = useState<View>('overview')
  const query = useQuery({ queryKey: ['dashboard'], queryFn: () => getDashboard(session.token) })
  const alerts = useQuery({ queryKey: ['alerts'], queryFn: () => getAlerts(session.token), enabled: view === 'security' })
  const nav: Array<[View, string, typeof Activity]> = [['overview', 'Overview', Activity], ['suppliers', 'Suppliers', Truck], ['security', 'Security lab', ShieldCheck], ['approvals', 'Approvals', PackageCheck], ['audit', 'Audit trail', FileClock]]
  return <div className="app-shell"><aside><div className="brand-mark"><ShieldCheck size={23}/><span>SentinelChain <b>AI</b></span></div><nav>{nav.map(([id, label, Icon]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}><Icon size={18}/><span>{label}</span>{id === 'approvals' && query.data?.kpis.pending_approvals ? <em>{query.data.kpis.pending_approvals}</em> : null}</button>)}</nav><div className="sidebar-footer"><div className="user-avatar">{session.user.display_name.split(' ').map((part) => part[0]).join('').slice(0,2)}</div><div><strong>{session.user.display_name}</strong><small>{roleLabel[session.user.role] ?? session.user.role}</small></div><button aria-label="Log out" onClick={onLogout}><LogOut size={17}/></button></div></aside><main className="workspace">{query.isLoading && <div className="loading"><div className="spinner"/>Loading verified data…</div>}{query.error && <div className="error-banner">{query.error.message}</div>}{query.data && view === 'overview' && <Overview data={query.data} token={session.token}/>} {view === 'suppliers' && <Suppliers token={session.token}/>} {view === 'security' && <><SecurityLab token={session.token}/>{alerts.data && <div className="lab-footnote">{alerts.data.length} total alert records preserved.</div>}</>} {query.data && view === 'approvals' && <Approvals data={query.data} token={session.token}/>} {view === 'audit' && <Audit token={session.token}/>}</main></div>
}

export default function App() {
  const saved = sessionStorage.getItem('sentinel-session')
  const [session, setSession] = useState<Session | null>(() => saved ? JSON.parse(saved) : null)
  function handleLogin(next: Session) { sessionStorage.setItem('sentinel-session', JSON.stringify(next)); setSession(next) }
  function logout() { sessionStorage.removeItem('sentinel-session'); setSession(null) }
  return session ? <Shell session={session} onLogout={logout}/> : <Login onLogin={handleLogin}/>
}

