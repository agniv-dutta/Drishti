import React, { useEffect, useState } from 'react';
import { AlertTriangle, BellRing, CalendarClock, ChevronDown, ChevronUp, CreditCard, LoaderCircle, Mail, RotateCcw, ShieldAlert } from 'lucide-react';
import { subscriptionsAPI, type SubscriptionPayment } from '../services/api';
import './SubscriptionsPage.css';

const merchantId = import.meta.env.VITE_MERCHANT_ID || 'demo-merchant';
const currency = (value: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value);
const dateLabel = (value: string | null) => value ? new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' }).format(new Date(value)) : 'Not scheduled';

const riskLabel = (risk: number) => risk > 0.7 ? 'high' : risk > 0.4 ? 'medium' : 'low';

const SubscriptionsPage: React.FC = () => {
  const [payments, setPayments] = useState<SubscriptionPayment[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    void subscriptionsAPI.list(merchantId)
      .then((data) => setPayments(data.payments))
      .catch(() => setError('Subscription recovery data is temporarily unavailable.'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleFailure = async (paymentId: string) => {
    setWorkingId(paymentId);
    setError(null);
    try { await subscriptionsAPI.handleFailure(paymentId); load(); }
    catch { setError('The recovery action could not be started.'); }
    finally { setWorkingId(null); }
  };

  const retrying = payments.filter((payment) => payment.status === 'retrying').length;
  const highRisk = payments.filter((payment) => payment.churn_risk > 0.7).length;
  const formatText = (value: string) => value.split('_').join(' ');

  return (
    <div className="subscriptions-page">
      <header className="subscriptions-topbar"><a href="#/dashboard/overview" className="subscriptions-brand"><span>D</span>Drishti</a><nav><a href="#/dashboard/overview">Operations</a><a className="active" href="#/subscriptions">Subscriptions</a><a href="#/receivables">Receivables</a><a href="#/dashboard/analytics">Analytics</a></nav><a href="#/page/client-login" className="subscriptions-login">Client login</a></header>
      <main className="subscriptions-main">
        <section className="subscriptions-heading"><div><p className="subscriptions-eyebrow">Recurring revenue protection</p><h1>Subscription recovery</h1><p>Keep committed customers active with progressive retries and timely card updates.</p></div><button type="button" className="subscriptions-refresh" onClick={load}><RotateCcw size={16} />Refresh data</button></section>
        <section className="subscription-summary"><article><span>Failed renewals</span><strong>{loading ? <LoaderCircle className="subscription-spinner" size={22} /> : payments.length}</strong><small>Requiring attention</small></article><article><span>Automatic retries</span><strong>{retrying}</strong><small>In the recovery queue</small></article><article><span>High churn risk</span><strong>{highRisk}</strong><small>Customers needing care</small></article><article><span>Recovery cadence</span><strong>3 steps</strong><small>T+3h · T+24h · T+72h</small></article></section>
        {error && <div className="subscriptions-error" role="alert">{error}</div>}
        <section className="subscriptions-panel"><div className="subscriptions-panel-heading"><div><p className="subscriptions-eyebrow">Renewal queue</p><h2>Failed subscription payments</h2></div><span>{payments.length} records</span></div><div className="subscriptions-table-wrap"><table className="subscriptions-table"><thead><tr><th>Customer</th><th>Subscription</th><th>Amount</th><th>Cycle</th><th>Churn risk</th><th>Retry schedule</th><th>Status</th><th /></tr></thead><tbody>{payments.map((payment) => { const expanded = expandedId === payment.id; const risk = riskLabel(payment.churn_risk); const warning = payment.retry_count >= 3; return <React.Fragment key={payment.id}><tr className={expanded ? 'is-expanded' : ''}><td><strong>{payment.customer_name}</strong><small>{payment.customer_email}</small></td><td><strong>{payment.subscription_name}</strong><small>Cycle {payment.billing_cycle} · {payment.failure_reason.replaceAll('_', ' ')}</small></td><td className="subscription-amount">{currency(payment.amount)}</td><td>#{payment.billing_cycle}</td><td><span className={`churn-risk ${risk}`}><i />{Math.round(payment.churn_risk * 100)}% {risk}</span></td><td><div className="retry-schedule">{payment.retry_schedule.map((step, index) => <span className={index < payment.retry_count ? 'complete' : ''} key={step}><b>{step}</b>{index < payment.retry_count ? 'done' : 'next'}</span>)}</div></td><td><span className={`subscription-status ${payment.status}`}>{warning ? 'suspension warning' : payment.status}</span></td><td><div className="subscription-actions"><button type="button" title={warning ? 'Send suspension warning' : 'Start next recovery step'} onClick={() => void handleFailure(payment.id)} disabled={workingId === payment.id}>{workingId === payment.id ? <LoaderCircle className="subscription-spinner" size={15} /> : warning ? <ShieldAlert size={15} /> : <BellRing size={15} />}</button><button type="button" title="View recovery history" onClick={() => setExpandedId(expanded ? null : payment.id)}>{expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</button></div></td></tr>{expanded && <tr className="subscription-detail-row"><td colSpan={8}><div className="subscription-detail-grid"><div><h3><CalendarClock size={15} /> What happens next</h3><p>{payment.next_retry_at ? `Next retry scheduled for ${dateLabel(payment.next_retry_at)}.` : warning ? 'Subscription suspension warning has been issued.' : 'Recovery action is ready to start.'}</p><p>Retry count: {payment.retry_count} of {payment.retry_schedule.length}</p></div><div><h3><Mail size={15} /> Card update prompt</h3><p>{payment.retry_count >= 2 ? 'Card update prompt is active.' : 'Prompt activates after the second failed retry.'}</p><p>Last action: {payment.last_action?.replaceAll('_', ' ') || 'None yet'}</p></div><div><h3><CreditCard size={15} /> Recovery history</h3>{payment.events.length ? payment.events.map((event) => <p key={event.id}><strong>{event.action.replaceAll('_', ' ')}</strong> · {event.status}</p>) : <p>No recovery action recorded.</p>}</div></div></td></tr>}</React.Fragment>; })}{!loading && payments.length === 0 && <tr><td colSpan={8} className="subscriptions-empty"><AlertTriangle size={22} />No failed subscriptions found.</td></tr>}</tbody></table></div></section>
      </main>
    </div>
  );
};

export default SubscriptionsPage;