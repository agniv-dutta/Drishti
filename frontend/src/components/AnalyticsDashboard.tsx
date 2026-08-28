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
import { Activity, AlertTriangle, Bell, ChevronDown, Clock3, Grid3x3, LayoutDashboard, LogOut, RefreshCw, Settings, Wallet } from 'lucide-react';
import { metricsAPI } from '../services/api';
import './AnalyticsDashboard.css';

type AnalyticsSummary = {
  recovery_rate: number;
  model_drift_score: number;
  total_payments_attempted: number;
  payments_recovered: number;
  cost_per_recovery_inr: number;
  channel_costs_inr: Record<string, number>;
};

const fallbackSummary: AnalyticsSummary = {
  recovery_rate: 0.58,
  model_drift_score: 0.08,
  total_payments_attempted: 1245,
  payments_recovered: 722,
  cost_per_recovery_inr: 420,
  channel_costs_inr: { sms: 6840, voice_ivr: 12100, email: 3200, offer: 8900 },
};

const funnel = [
  { label: 'Payments ingested', value: 1245, fill: '#ff7359' },
  { label: 'AI analyzed', value: 1188, fill: '#f59d6c' },
  { label: 'Strategy selected', value: 1140, fill: '#e7bd78' },
  { label: 'Recovery executed', value: 1018, fill: '#96b89f' },
  { label: 'Revenue recovered', value: 722, fill: '#6e9d85' },
];
const strategies = [
  { name: 'Retry', success: 45, contacts: 384 },
  { name: 'SMS', success: 58, contacts: 496 },
  { name: 'Call', success: 72, contacts: 138 },
  { name: 'Offer', success: 64, contacts: 96 },
];
const trend = [
  { day: 'Mon', revenue: 410000 }, { day: 'Tue', revenue: 530000 }, { day: 'Wed', revenue: 470000 },
  { day: 'Thu', revenue: 690000 }, { day: 'Fri', revenue: 610000 }, { day: 'Sat', revenue: 760000 }, { day: 'Sun', revenue: 820000 },
];
const timeBuckets = ['6a', '9a', '12p', '3p', '6p', '9p'];
const heatmap = [
  [18, 24, 42, 35, 48, 71, 74], [21, 28, 44, 39, 53, 68, 72], [16, 26, 51, 41, 55, 76, 79],
  [14, 22, 46, 37, 50, 73, 77], [19, 30, 48, 43, 57, 69, 75], [12, 18, 39, 33, 45, 66, 70],
];
const costColors = ['#ff7359', '#e7bd78', '#96b89f', '#c88272'];

const currency = (value: number) => `Rs ${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value)}`;
const percent = (value: number) => `${Math.round(value * 100)}%`;

const AnalyticsDashboard: React.FC = () => {
  const [summary, setSummary] = useState(fallbackSummary);
  const [connected, setConnected] = useState(false);
  const [period, setPeriod] = useState(30);

  useEffect(() => {
    let active = true;
    void metricsAPI.getSummary(period).then(({ data }) => {
      if (!active) return;
      setSummary({ ...fallbackSummary, ...data } as AnalyticsSummary);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [period]);

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
        try { setSummary((current) => ({ ...current, ...JSON.parse(event.data) })); } catch { /* keep last good snapshot */ }
      };
    } catch { setConnected(false); }
    return () => socket?.close();
  }, []);

  const pieData = useMemo(() => Object.entries(summary.channel_costs_inr).map(([name, value]) => ({ name: name.replace('_', ' '), value })), [summary.channel_costs_inr]);
  const recoveryRate = summary.recovery_rate || fallbackSummary.recovery_rate;
  const alertItems = [
    recoveryRate < 0.5 && { tone: 'warning', icon: <AlertTriangle size={16} />, text: `Recovery rate dropped to ${percent(recoveryRate)} today. Investigate?` },
    summary.model_drift_score > 0.15 && { tone: 'danger', icon: <Bell size={16} />, text: 'Strategy performance changed. Retrain recommended.' },
    { tone: 'notice', icon: <Activity size={16} />, text: '3 complaints about SMS today. Review templates?' },
  ].filter(Boolean) as Array<{ tone: string; icon: React.ReactNode; text: string }>;

  return (
    <div className="analytics-page">
      <header className="analytics-topbar">
        <a href="#/" className="analytics-brand" aria-label="Back to home"><span className="analytics-brand-mark">V</span><span>Drishti</span></a>
        <nav className="analytics-nav" aria-label="Primary"><a href="#/dashboard/overview">Operations</a><a className="active" href="#/dashboard/analytics">Analytics</a><a href="#/page/integrations">Integrations</a><a href="#/page/company">Company</a></nav>
        <div className="analytics-top-actions"><span className={`live-status ${connected ? 'connected' : ''}`}><i />{connected ? 'Live' : 'Snapshot'}</span><a href="#/page/client-login">Client Login</a></div>
      </header>
      <div className="analytics-layout">
        <aside className="analytics-sidebar" aria-label="Sidebar navigation">
          <div>
            <p className="analytics-sidebar-label">Workspace</p>
            <a href="#/dashboard/overview"><LayoutDashboard size={17} />Overview</a>
            <a href="#/dashboard/payments"><Wallet size={17} />Payments</a>
            <a href="#/dashboard/recoveries"><RefreshCw size={17} />Recoveries</a>
            <a className="active" href="#/dashboard/analytics"><Grid3x3 size={17} />Analytics</a>
            <a href="#/dashboard/audit-trail"><Activity size={17} />Audit trail</a>
          </div>
          <div><a href="#/dashboard/settings"><Settings size={17} />Settings</a><button type="button" onClick={() => { window.location.hash = '#/'; }}><LogOut size={17} />Log out</button></div>
        </aside>
        <main className="analytics-main">
          <section className="analytics-heading"><div><p className="analytics-eyebrow">Performance intelligence</p><h1>Recovery analytics</h1><p>One view of conversion, cost, timing, and customer friction.</p></div><label className="period-select"><Clock3 size={16} /><select value={period} onChange={(event) => setPeriod(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select><ChevronDown size={15} /></label></section>
          <section className="analytics-kpis"><article><span>Recovery rate</span><strong>{percent(recoveryRate)}</strong><small className="up">+6.4% vs prior period</small></article><article><span>Revenue recovered</span><strong>{currency(4290000)}</strong><small>722 successful payments</small></article><article><span>Avg cost / recovery</span><strong>{currency(summary.cost_per_recovery_inr || 420)}</strong><small>-19% vs prior period</small></article><article><span>Time to recovery</span><strong>6h 42m</strong><small>Median, all strategies</small></article></section>
          {alertItems.length > 0 && <section className="analytics-alerts" aria-label="Alerts">{alertItems.map((alert) => <div className={`analytics-alert ${alert.tone}`} key={alert.text}>{alert.icon}<span>{alert.text}</span><button type="button" aria-label="Dismiss alert">×</button></div>)}</section>}
          <section className="analytics-grid analytics-grid-top"><article className="analytics-panel funnel-panel"><div className="panel-heading"><div><p className="panel-kicker">Drop-off analysis</p><h2>Recovery funnel</h2></div><span>Today</span></div><ResponsiveContainer width="100%" height={240}><BarChart layout="vertical" data={funnel} margin={{ left: 18, right: 28 }}><CartesianGrid horizontal={false} stroke="#eadfd6" /><XAxis type="number" hide /><YAxis type="category" dataKey="label" width={120} tick={{ fill: '#675f5b', fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: '#fff8f3' }} formatter={(value) => [value, 'payments']} /><Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={24}>{funnel.map((entry) => <Cell key={entry.label} fill={entry.fill} />)}</Bar></BarChart></ResponsiveContainer></article><article className="analytics-panel"><div className="panel-heading"><div><p className="panel-kicker">Conversion by play</p><h2>Strategy performance</h2></div><span>Success rate</span></div><ResponsiveContainer width="100%" height={240}><BarChart data={strategies} margin={{ top: 12, right: 4, left: -22 }}><CartesianGrid vertical={false} stroke="#eadfd6" /><XAxis dataKey="name" tick={{ fill: '#675f5b', fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis domain={[0, 80]} tickFormatter={(value) => `${value}%`} tick={{ fill: '#8b817b', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => [`${value}%`, 'success']} /><Bar dataKey="success" fill="#ff7359" radius={[4, 4, 0, 0]} barSize={34} /></BarChart></ResponsiveContainer></article></section>
          <section className="analytics-grid analytics-grid-middle"><article className="analytics-panel trend-panel"><div className="panel-heading"><div><p className="panel-kicker">Cash recovered</p><h2>Revenue trend</h2></div><strong>{currency(4290000)}</strong></div><ResponsiveContainer width="100%" height={215}><LineChart data={trend} margin={{ top: 16, right: 10, left: -8 }}><CartesianGrid vertical={false} stroke="#eadfd6" /><XAxis dataKey="day" tick={{ fill: '#8b817b', fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(value) => `${value / 1000}k`} tick={{ fill: '#8b817b', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => [currency(Number(value)), 'recovered']} /><Line type="monotone" dataKey="revenue" stroke="#2d1b4e" strokeWidth={3} dot={{ r: 3, fill: '#ff7359', strokeWidth: 0 }} /></LineChart></ResponsiveContainer></article><article className="analytics-panel cost-panel"><div className="panel-heading"><div><p className="panel-kicker">Unit economics</p><h2>Cost mix</h2></div></div><div className="cost-chart"><ResponsiveContainer width="52%" height={170}><PieChart><Pie data={pieData} dataKey="value" innerRadius={45} outerRadius={70} paddingAngle={3}>{pieData.map((entry, index) => <Cell key={entry.name} fill={costColors[index % costColors.length]} />)}</Pie><Tooltip formatter={(value) => [currency(Number(value)), 'cost']} /></PieChart></ResponsiveContainer><div className="cost-legend">{pieData.map((entry, index) => <div key={entry.name}><i style={{ background: costColors[index % costColors.length] }} /><span>{entry.name}</span><strong>{currency(entry.value)}</strong></div>)}</div></div></article></section>
          <section className="analytics-grid analytics-grid-bottom"><article className="analytics-panel heat-panel"><div className="panel-heading"><div><p className="panel-kicker">Local customer time</p><h2>Contact heatmap</h2></div><span>Recovery success %</span></div><div className="heatmap"><div /><div className="heat-days">{['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>{heatmap.map((row, rowIndex) => <React.Fragment key={timeBuckets[rowIndex]}><span className="heat-time">{timeBuckets[rowIndex]}</span>{row.map((value, colIndex) => <span className="heat-cell" title={`${value}% success`} style={{ opacity: 0.25 + value / 100 }} key={`${rowIndex}-${colIndex}`}>{value}</span>)}</React.Fragment>)}</div></article><article className="analytics-panel segment-panel"><div className="panel-heading"><div><p className="panel-kicker">Who converts</p><h2>Segments & regions</h2></div></div><div className="segment-list"><div><span>Retained customers</span><strong>68%</strong><em>+14%</em></div><div><span>New customers</span><strong>41%</strong><em>+5%</em></div><div><span>Mumbai</span><strong>63%</strong><em>+9%</em></div><div><span>Bangalore</span><strong>59%</strong><em>+6%</em></div><div><span>Tier-2 cities</span><strong>48%</strong><em>+3%</em></div></div></article></section>
          <footer className="analytics-footer"><span>Last updated just now</span><button type="button" onClick={() => setPeriod(period)}> <RefreshCw size={14} />Refresh data</button></footer>
        </main>
      </div>
    </div>
  );
};

export default AnalyticsDashboard;
