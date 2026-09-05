import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDownUp, BellRing, Building2, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clock3, FileText, Grid3x3, LayoutDashboard, LoaderCircle, LogOut, Mail, RefreshCw, Settings, ShieldAlert, Wallet, WalletCards } from 'lucide-react';
import { receivablesAPI, type DsoMetrics, type ReceivablesInvoice } from '../services/api';
import './ReceivablesPage.css';

type SortKey = 'amount' | 'days_overdue' | 'due_date';

const merchantId = import.meta.env.VITE_MERCHANT_ID || 'demo-merchant';
const currency = (value: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value);
const dateLabel = (value: string) => new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(value));

const ReceivablesPage: React.FC = () => {
  const [invoices, setInvoices] = useState<ReceivablesInvoice[]>([]);
  const [dso, setDso] = useState<DsoMetrics | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('days_overdue');
  const [descending, setDescending] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try { return localStorage.getItem('sidebar_open') !== 'false'; } catch { return true; }
  });

  const toggleSidebar = () => {
    setSidebarOpen((current) => {
      const next = !current;
      try { localStorage.setItem('sidebar_open', String(next)); } catch { /* noop */ }
      return next;
    });
  };

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([receivablesAPI.list(merchantId, sortKey, descending), receivablesAPI.dso(merchantId)])
      .then(([invoiceData, dsoData]) => {
        setInvoices(invoiceData.invoices);
        setDso(dsoData);
      })
      .catch(() => setError('Receivables data is temporarily unavailable.'))
      .finally(() => setLoading(false));
  };

  useEffect(load, [sortKey, descending]);

  const overdueTotal = useMemo(() => invoices.filter((invoice) => invoice.days_overdue > 0).reduce((sum, invoice) => sum + invoice.amount, 0), [invoices]);

  const sort = (key: SortKey) => {
    if (key === sortKey) setDescending((current) => !current);
    else { setSortKey(key); setDescending(true); }
  };

  const sendReminder = async (invoiceId: string) => {
    setSendingId(invoiceId);
    try {
      await receivablesAPI.sendReminder(invoiceId);
      load();
    } catch { setError('Reminder could not be sent.'); }
    finally { setSendingId(null); }
  };

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
            <a href="#/receivables" className="dashboard-sidebar-item active">
              <Wallet size={18} />
              <span className="dashboard-sidebar-text">Receivables</span>
            </a>
            <a href="#/subscriptions" className="dashboard-sidebar-item">
              <RefreshCw size={18} />
              <span className="dashboard-sidebar-text">Subscriptions</span>
            </a>
            <a href="#/dashboard/analytics" className="dashboard-sidebar-item">
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
              <p className="dashboard-eyebrow">B2B cash flow control</p>
              <h2>Receivables recovery</h2>
              <p>Detect overdue invoices, coordinate reminders, and keep payment promises visible.</p>
            </div>
            <button type="button" className="receivables-refresh" onClick={load}><Clock3 size={16} />Refresh data</button>
          </section>

          <section className="receivables-kpis">
            <article className="receivables-kpi receivables-kpi-coral"><span>Days sales outstanding</span><strong>{dso ? `${dso.dso} days` : <LoaderCircle className="receivables-spinner" size={23} />}</strong><small>Target {dso?.benchmark ?? 45} days</small></article>
            <article className="receivables-kpi receivables-kpi-gold"><span>Overdue exposure</span><strong>{currency(dso?.total_overdue_amount ?? overdueTotal)}</strong><small>{dso?.overdue_invoices ?? 0} invoices at risk</small></article>
            <article className="receivables-kpi receivables-kpi-sage"><span>Accounts receivable</span><strong>{currency(dso?.total_accounts_receivable ?? 0)}</strong><small>{dso?.improvement ?? 'Live portfolio view'}</small></article>
            <article className="receivables-kpi receivables-kpi-rose"><span>Promise coverage</span><strong>{invoices.filter((invoice) => invoice.payment_promises.length > 0).length}/{invoices.length}</strong><small>Invoices with payment promises</small></article>
          </section>

          {error && <div className="receivables-error" role="alert">{error}</div>}
          <section className="receivables-panel">
            <div className="receivables-panel-heading"><div><p className="receivables-eyebrow">Collections queue</p><h2>Overdue invoices</h2></div><span>{loading ? 'Updating...' : `${invoices.length} invoices`}</span></div>
            <div className="receivables-table-wrap">
              <table className="receivables-table">
                <thead><tr><th>Invoice</th><th>Customer</th><th><button type="button" onClick={() => sort('amount')}>Amount <ArrowDownUp size={13} /></button></th><th><button type="button" onClick={() => sort('days_overdue')}>Overdue <ArrowDownUp size={13} /></button></th><th>Status</th><th>Next action</th><th aria-label="Actions" /></tr></thead>
                <tbody>
                  {invoices.map((invoice) => {
                    const expanded = expandedId === invoice.id;
                    const escalated = invoice.recommended_action === 'escalate';
                    return <React.Fragment key={invoice.id}>
                      <tr className={expanded ? 'is-expanded' : ''}>
                        <td><strong>{invoice.invoice_number}</strong><small>Due {dateLabel(invoice.due_date)}</small></td>
                        <td><strong>{invoice.customer_name}</strong><small>{invoice.contact_name}</small></td>
                        <td className="amount-cell">{currency(invoice.amount)}</td>
                        <td><span className={`overdue-count ${escalated ? 'critical' : ''}`}>{invoice.days_overdue}d</span></td>
                        <td><span className={`invoice-status ${invoice.status}`}>{invoice.status.replace('_', ' ')}</span></td>
                        <td><span className="next-action">{escalated ? <ShieldAlert size={15} /> : <BellRing size={15} />}{escalated ? 'Escalate' : 'Remind'}</span></td>
                        <td><div className="invoice-actions"><button type="button" title="Send reminder" onClick={() => void sendReminder(invoice.id)} disabled={sendingId === invoice.id}><Mail size={16} /></button><button type="button" title="View history" onClick={() => setExpandedId(expanded ? null : invoice.id)}>{expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button></div></td>
                      </tr>
                      {expanded && <tr className="invoice-detail-row"><td colSpan={7}><div className="invoice-detail-grid"><div><h3><Mail size={15} /> Reminder history</h3>{invoice.reminders.length ? invoice.reminders.map((reminder) => <p key={reminder.id}>{reminder.template.replace('_', ' ')} <small>{dateLabel(reminder.sent_at)} · {reminder.status}</small></p>) : <p>No reminders sent yet.</p>}</div><div><h3><WalletCards size={15} /> Payment promises</h3>{invoice.payment_promises.length ? invoice.payment_promises.map((promise) => <p key={promise.id}>{currency(promise.promised_amount)} by {dateLabel(promise.promised_date)} <small>{promise.status}</small></p>) : <p>No promise recorded.</p>}</div><div><h3><FileText size={15} /> Recovery signals</h3><p>Risk score <strong>{Math.round(invoice.risk_score * 100)}%</strong></p><p>{invoice.reminder_count} reminder{invoice.reminder_count === 1 ? '' : 's'} sent</p></div></div></td></tr>}
                    </React.Fragment>;
                  })}
                  {!loading && invoices.length === 0 && <tr><td colSpan={7} className="receivables-empty"><Building2 size={22} />No invoices found for this merchant.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
};

export default ReceivablesPage;