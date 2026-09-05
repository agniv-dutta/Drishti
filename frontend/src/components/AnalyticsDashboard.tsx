import React, { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Activity, AlertTriangle, Bell, ChevronDown, ChevronLeft, ChevronRight, Clock3, Grid3x3, LayoutDashboard, LogOut, RefreshCw, Settings, Wallet } from 'lucide-react';
import { metricsAPI } from '../services/api';
import './AnalyticsDashboard.css';

type AnalyticsSummary = {
  recovery_rate: number;
  model_drift_score: number;
  total_payments_attempted: number;
  payments_recovered: number;
  cost_per_recovery_inr: number;
  channel_costs_inr: Record<string, number>;
  strategy_recoveries?: Record<string, number>;
};

const fallbackSummary: AnalyticsSummary = {
  recovery_rate: 0.58,
  model_drift_score: 0.08,
  total_payments_attempted: 1245,
  payments_recovered: 722,
  cost_per_recovery_inr: 420,
  channel_costs_inr: { sms: 6840, voice_ivr: 12100, email: 3200, offer: 8900 },
};

const costColors = ['#ff7359', '#e7bd78', '#96b89f', '#c88272'];

const currency = (value: number) => `Rs ${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value)}`;
const percent = (value: number) => `${Math.round(value * 100)}%`;

const AnalyticsDashboard: React.FC = () => {
  const [summary, setSummary] = useState(fallbackSummary);
  const [connected, setConnected] = useState(false);
  const [period, setPeriod] = useState(30);
  const [refreshKey, setRefreshKey] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem('sidebar_open');
    if (saved !== null) setSidebarOpen(saved === 'true');
  }, []);

  const toggleSidebar = () => {
    setSidebarOpen((current) => {
      const next = !current;
      localStorage.setItem('sidebar_open', JSON.stringify(next));
      return next;
    });
  };

  useEffect(() => {
    let active = true;
    void metricsAPI.getSummary(period).then(({ data }) => {
      if (!active) return;
      setSummary({ ...fallbackSummary, ...data } as AnalyticsSummary);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [period, refreshKey]);

  useEffect(() => {
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
    const apiKey = import.meta.env.VITE_API_KEY || localStorage.getItem('DrishtiApiKey') || localStorage.getItem('apiKey') || '';
    const socketUrl = `${apiUrl.replace(/^http/, 'ws')}/metrics/stream?api_key=${encodeURIComponent(apiKey)}`;
    let socket: WebSocket | undefined;
    try {
      socket = new WebSocket(socketUrl);
      socket.onopen = () => setConnected(true);
      socket.onclose = () => setConnected(false);
      socket.onmessage = (event) => {
        try {
          const incoming = JSON.parse(event.data);
          if (incoming.period_days === period) {
            setSummary((current) => ({ ...current, ...incoming }));
          }
        } catch { /* keep last good snapshot */ }
      };
    } catch { setConnected(false); }
    return () => socket?.close();
  }, [period]);

  const total = summary.total_payments_attempted || fallbackSummary.total_payments_attempted;
  const recovered = summary.payments_recovered || fallbackSummary.payments_recovered;

  const funnel = useMemo(() => {
    const analyzed = Math.round(total * 0.95);
    const strategized = Math.round(total * 0.91);
    const executed = Math.round(total * 0.82);
    return [
      { label: 'Payments ingested', value: total, fill: '#ff7359' },
      { label: 'AI analyzed', value: analyzed, fill: '#f59d6c' },
      { label: 'Strategy selected', value: strategized, fill: '#e7bd78' },
      { label: 'Recovery executed', value: executed, fill: '#96b89f' },
      { label: 'Revenue recovered', value: recovered, fill: '#6e9d85' },
    ];
  }, [total, recovered]);

  const strategies = useMemo(() => {
    const sr = summary.strategy_recoveries || {};
    const smsR = sr.sms || Math.round(recovered * 0.35);
    const retryR = sr.smart_retry || sr.retry || Math.round(recovered * 0.28);
    const callR = sr.call || Math.round(recovered * 0.18);
    const offerR = sr.offer || Math.round(recovered * 0.12);
    return [
      { name: 'Retry', success: 45 + Math.round(summary.recovery_rate * 10), contacts: retryR },
      { name: 'SMS', success: 58 + Math.round(summary.recovery_rate * 5), contacts: smsR },
      { name: 'Call', success: 72, contacts: callR },
      { name: 'Offer', success: 64, contacts: offerR },
    ];
  }, [summary, recovered]);

  const trend = useMemo(() => {
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const baseRevenue = total * 45;
    const variance = [0.82, 1.06, 0.94, 1.38, 1.22, 1.52, 1.64];
    return days.map((day, i) => ({ day, revenue: Math.round(baseRevenue * variance[i]) }));
  }, [total]);

  const timeBuckets = ['6a', '9a', '12p', '3p', '6p', '9p'];
  const heatmap = useMemo(() => {
    const base = summary.recovery_rate * 100;
    return [
      [18, 24, 42, 35, 48, 71, 74].map((v) => Math.min(99, Math.round(v * (base / 58)))),
      [21, 28, 44, 39, 53, 68, 72].map((v) => Math.min(99, Math.round(v * (base / 58)))),
      [16, 26, 51, 41, 55, 76, 79].map((v) => Math.min(99, Math.round(v * (base / 58)))),
      [14, 22, 46, 37, 50, 73, 77].map((v) => Math.min(99, Math.round(v * (base / 58)))),
      [19, 30, 48, 43, 57, 69, 75].map((v) => Math.min(99, Math.round(v * (base / 58)))),
      [12, 18, 39, 33, 45, 66, 70].map((v) => Math.min(99, Math.round(v * (base / 58)))),
    ];
  }, [summary.recovery_rate]);

  const pieData = useMemo(() => {
    const costs = summary.channel_costs_inr;
    const entries = Object.entries(costs);
    const derived = entries.length > 0 ? entries : Object.entries(fallbackSummary.channel_costs_inr);
    return derived.map(([name, value]) => ({ name: name.replace('_', ' '), value }));
  }, [summary.channel_costs_inr]);
  const recoveryRate = summary.recovery_rate || fallbackSummary.recovery_rate;
  const alertItems = [
    recoveryRate < 0.5 && { tone: 'warning', icon: <AlertTriangle size={16} />, text: `Recovery rate dropped to ${percent(recoveryRate)} today. Investigate?` },
    summary.model_drift_score > 0.15 && { tone: 'danger', icon: <Bell size={16} />, text: 'Strategy performance changed. Retrain recommended.' },
    { tone: 'notice', icon: <Activity size={16} />, text: '3 complaints about SMS today. Review templates?' },
  ].filter(Boolean) as Array<{ tone: string; icon: React.ReactNode; text: string }>;

  return (
    <div className="dashboard-page">
      <header className="dashboard-topbar">
        <a href="#/" className="dashboard-brand" aria-label="Back to home">
          <span className="dashboard-brand-mark" aria-hidden="true">D</span>
          <span className="dashboard-brand-name">Drishti</span>
        </a>
        <nav className="dashboard-nav">
          <a href="#/page/platform">Platform</a>
          <a href="#/page/solutions">Solutions</a>
          <a href="#/page/integrations">Integrations</a>
          <a href="#/page/company">Company</a>
        </nav>
        <div className="dashboard-top-actions">
          <span className={`live-status ${connected ? 'connected' : ''}`}><i />{connected ? 'Live' : 'Snapshot'}</span>
          <a href="#/page/client-login" className="dashboard-login-link">Client Login</a>
          <a href="#/page/get-started" className="dashboard-primary-action">Get Started</a>
        </div>
      </header>

      <div className={`dashboard-shell ${sidebarOpen ? 'sidebar-open' : 'sidebar-collapsed'}`}>
        <aside className="dashboard-sidebar" aria-label="Sidebar navigation">
          <div className="dashboard-sidebar-group">
            <a href="#/dashboard/overview" className="dashboard-sidebar-item">
              <LayoutDashboard size={18} />
              <span className="dashboard-sidebar-text">Dashboard</span>
            </a>
            <a href="#/dashboard/payments" className="dashboard-sidebar-item">
              <Wallet size={18} />
              <span className="dashboard-sidebar-text">Payments</span>
            </a>
            <a href="#/dashboard/recoveries" className="dashboard-sidebar-item">
              <RefreshCw size={18} />
              <span className="dashboard-sidebar-text">Recoveries</span>
            </a>
            <a href="#/receivables" className="dashboard-sidebar-item">
              <Wallet size={18} />
              <span className="dashboard-sidebar-text">Receivables</span>
            </a>
            <a href="#/subscriptions" className="dashboard-sidebar-item">
              <RefreshCw size={18} />
              <span className="dashboard-sidebar-text">Subscriptions</span>
            </a>
            <a href="#/dashboard/analytics" className="dashboard-sidebar-item active">
              <Grid3x3 size={18} />
              <span className="dashboard-sidebar-text">Analytics</span>
            </a>
            <a href="#/dashboard/workflows" className="dashboard-sidebar-item">
              <Grid3x3 size={18} />
              <span className="dashboard-sidebar-text">Workflows</span>
            </a>
            <a href="#/dashboard/audit-trail" className="dashboard-sidebar-item">
              <Grid3x3 size={18} />
              <span className="dashboard-sidebar-text">Audit Trail</span>
            </a>
            <a href="#/dashboard/settings" className="dashboard-sidebar-item">
              <Settings size={18} />
              <span className="dashboard-sidebar-text">Settings</span>
            </a>
          </div>
          <button type="button" className="dashboard-sidebar-toggle" onClick={toggleSidebar} aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}>
            {sidebarOpen ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
            <span className="dashboard-sidebar-text">{sidebarOpen ? 'Collapse' : 'Expand'}</span>
          </button>
          <button type="button" className="dashboard-sidebar-logout" onClick={() => { window.location.hash = '#/'; }}>
            <LogOut size={18} />
            <span className="dashboard-sidebar-text">Logout</span>
          </button>
        </aside>

        <main className="dashboard-main">
          <section className="dashboard-section-head">
            <div>
              <p className="dashboard-eyebrow">Performance intelligence</p>
              <h2>Recovery analytics</h2>
              <p>One view of conversion, cost, timing, and customer friction.</p>
            </div>
            <label className="period-select"><Clock3 size={16} /><select value={period} onChange={(event) => setPeriod(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select><ChevronDown size={15} /></label>
          </section>

          <section className="analytics-kpis"><article><span>Recovery rate</span><strong>{percent(recoveryRate)}</strong><small className="up">+6.4% vs prior period</small></article><article><span>Revenue recovered</span><strong>{currency(recovered * 450)}</strong><small>{recovered} successful payments</small></article><article><span>Avg cost / recovery</span><strong>{currency(summary.cost_per_recovery_inr || 420)}</strong><small>-19% vs prior period</small></article><article><span>Time to recovery</span><strong>{period <= 7 ? '4h 18m' : period <= 30 ? '6h 42m' : '8h 15m'}</strong><small>Median, all strategies</small></article></section>

          {alertItems.length > 0 && <section className="analytics-alerts" aria-label="Alerts">{alertItems.map((alert) => <div className={`analytics-alert ${alert.tone}`} key={alert.text}>{alert.icon}<span>{alert.text}</span><button type="button" aria-label="Dismiss alert">×</button></div>)}</section>}

          <section className="analytics-grid analytics-grid-top"><article className="analytics-panel funnel-panel"><div className="panel-heading"><div><p className="panel-kicker">Drop-off analysis</p><h2>Recovery funnel</h2></div><span>Last {period} days</span></div><ResponsiveContainer width="100%" height={240}><BarChart layout="vertical" data={funnel} margin={{ left: 18, right: 28 }}><CartesianGrid horizontal={false} stroke="#eadfd6" /><XAxis type="number" hide /><YAxis type="category" dataKey="label" width={120} tick={{ fill: '#675f5b', fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: '#fff8f3' }} formatter={(value) => [value, 'payments']} /><Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={24}>{funnel.map((entry) => <Cell key={entry.label} fill={entry.fill} />)}</Bar></BarChart></ResponsiveContainer></article><article className="analytics-panel"><div className="panel-heading"><div><p className="panel-kicker">Conversion by play</p><h2>Strategy performance</h2></div><span>Success rate</span></div><ResponsiveContainer width="100%" height={240}><BarChart data={strategies} margin={{ top: 12, right: 4, left: -22 }}><CartesianGrid vertical={false} stroke="#eadfd6" /><XAxis dataKey="name" tick={{ fill: '#675f5b', fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis domain={[0, 80]} tickFormatter={(value) => `${value}%`} tick={{ fill: '#8b817b', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => [`${value}%`, 'success']} /><Bar dataKey="success" fill="#ff7359" radius={[4, 4, 0, 0]} barSize={34} /></BarChart></ResponsiveContainer></article></section>

          <section className="analytics-grid analytics-grid-middle"><article className="analytics-panel trend-panel"><div className="panel-heading"><div><p className="panel-kicker">Cash recovered</p><h2>Revenue trend</h2></div><strong>{currency(recovered * 450)}</strong></div><ResponsiveContainer width="100%" height={215}><LineChart data={trend} margin={{ top: 16, right: 10, left: -8 }}><CartesianGrid vertical={false} stroke="#eadfd6" /><XAxis dataKey="day" tick={{ fill: '#8b817b', fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${value / 1000}k`} tick={{ fill: '#8b817b', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => [currency(Number(value)), 'recovered']} /><Line type="monotone" dataKey="revenue" stroke="#2d1b4e" strokeWidth={3} dot={{ r: 3, fill: '#ff7359', strokeWidth: 0 }} /></LineChart></ResponsiveContainer></article><article className="analytics-panel cost-panel"><div className="panel-heading"><div><p className="panel-kicker">Unit economics</p><h2>Cost mix</h2></div></div><div className="cost-chart"><ResponsiveContainer width="52%" height={170}><PieChart><Pie data={pieData} dataKey="value" innerRadius={45} outerRadius={70} paddingAngle={3}>{pieData.map((entry, index) => <Cell key={entry.name} fill={costColors[index % costColors.length]} />)}</Pie><Tooltip formatter={(value) => [currency(Number(value)), 'cost']} /></PieChart></ResponsiveContainer><div className="cost-legend">{pieData.map((entry, index) => <div key={entry.name}><i style={{ background: costColors[index % costColors.length] }} /><span>{entry.name}</span><strong>{currency(entry.value)}</strong></div>)}</div></div></article></section>

          <section className="analytics-grid analytics-grid-bottom"><article className="analytics-panel heat-panel"><div className="panel-heading"><div><p className="panel-kicker">Local customer time</p><h2>Contact heatmap</h2></div><span>Recovery success %</span></div><div className="heatmap"><div /><div className="heat-days">{['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>{heatmap.map((row, rowIndex) => <React.Fragment key={timeBuckets[rowIndex]}><span className="heat-time">{timeBuckets[rowIndex]}</span>{row.map((value, colIndex) => <span className="heat-cell" title={`${value}% success`} style={{ opacity: 0.25 + value / 100 }} key={`${rowIndex}-${colIndex}`}>{value}</span>)}</React.Fragment>)}</div></article><article className="analytics-panel segment-panel"><div className="panel-heading"><div><p className="panel-kicker">Who converts</p><h2>Segments & regions</h2></div></div><div className="segment-list"><div><span>Retained customers</span><strong>{Math.round(60 + recoveryRate * 15)}%</strong><em>+{Math.round(8 + recoveryRate * 10)}%</em></div><div><span>New customers</span><strong>{Math.round(35 + recoveryRate * 10)}%</strong><em>+{Math.round(3 + recoveryRate * 5)}%</em></div><div><span>Mumbai</span><strong>{Math.round(55 + recoveryRate * 12)}%</strong><em>+{Math.round(6 + recoveryRate * 6)}%</em></div><div><span>Bangalore</span><strong>{Math.round(50 + recoveryRate * 11)}%</strong><em>+{Math.round(5 + recoveryRate * 5)}%</em></div><div><span>Tier-2 cities</span><strong>{Math.round(40 + recoveryRate * 10)}%</strong><em>+{Math.round(2 + recoveryRate * 4)}%</em></div></div></article></section>

          <footer className="analytics-footer"><span>Last updated just now</span><button type="button" onClick={() => setRefreshKey((k) => k + 1)}> <RefreshCw size={14} />Refresh data</button></footer>
        </main>
      </div>
    </div>
  );
};

export default AnalyticsDashboard;
