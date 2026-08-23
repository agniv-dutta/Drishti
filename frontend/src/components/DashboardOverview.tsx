import React, { useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowUpRight,
  BadgePercent,
  CalendarDays,
  ChevronDown,
  Grid3x3,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Settings,
  Wallet,
  RefreshCw,
} from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import type { Payment } from '../types/dashboard';
import './DashboardOverview.css';

const fallbackPayments: Payment[] = [
  { id: 'VR-8921', amount: 12500, status: 'failed', strategyUsed: 'automated_drip', recoveredAmount: 4000, lastUpdated: '2 hrs ago' },
  { id: 'VR-8910', amount: 85000, status: 'escalated', strategyUsed: 'concierge_call', recoveredAmount: 0, lastUpdated: '5 hrs ago' },
  { id: 'VR-8854', amount: 3200, status: 'recovered', strategyUsed: 'sms_reminder', recoveredAmount: 3200, lastUpdated: '1 day ago' },
  { id: 'VR-8848', amount: 12850, status: 'failed', strategyUsed: 'whatsapp_followup', recoveredAmount: 2200, lastUpdated: '2 days ago' },
];

const fallbackFeed = [
  { label: 'Payment #123', action: 'SMS sent to customer', amount: 'Rs 500 recovered', time: 'Just now', icon: 'MessageSquareText' },
  { label: 'Payment #VR-8910', action: 'Concierge call initiated', amount: 'Follow-up queued', time: '15 mins ago', icon: 'Phone' },
  { label: 'Payment #VR-8915', action: 'Automated email drip started', amount: 'New recovery path', time: '1 hr ago', icon: 'Mail' },
];

const formatCurrency = (value: number) =>
  new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(Math.round(value));

const statusLabel = (status: Payment['status']) =>
  status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ');

const DashboardOverview: React.FC = () => {
  const loadDashboard = useDashboardStore((state) => state.loadDashboard);
  const isLoading = useDashboardStore((state) => state.isLoading);
  const error = useDashboardStore((state) => state.error);
  const recoveryRate = useDashboardStore((state) => state.recoveryRate);
  const targetRate = useDashboardStore((state) => state.targetRate);
  const totalRecovered = useDashboardStore((state) => state.totalRecovered);
  const totalPaymentsProcessed = useDashboardStore((state) => state.totalPaymentsProcessed);
  const payments = useDashboardStore((state) => state.payments);
  const activityFeed = useDashboardStore((state) => state.activityFeed);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const openJourney = (paymentId: string) => {
    window.location.hash = `#/journey/${paymentId}`;
  };

  const cards = [
    {
      label: 'Total Payments Processed',
      value: totalPaymentsProcessed > 0 ? formatCurrency(totalPaymentsProcessed) : '1,245',
      delta: '+12%',
      detail: 'This week',
      icon: <BadgePercent size={18} />,
      tone: 'coral',
    },
    {
      label: 'Recovery Rate',
      value: `${(recoveryRate > 0 ? recoveryRate : 58).toFixed(0)}%`,
      delta: '',
      detail: `Target: ${(targetRate > 0 ? targetRate : 60).toFixed(0)}%`,
      icon: <RefreshCw size={18} />,
      tone: 'gold',
    },
    {
      label: 'Money Recovered',
      value: `Rs ${formatCurrency(totalRecovered > 0 ? totalRecovered : 4200000)}`,
      delta: 'vs last week',
      detail: '+10.5%',
      icon: <Wallet size={18} />,
      tone: 'sand',
    },
    {
      label: 'Avg Cost per Recovery',
      value: 'Rs 420',
      delta: 'Down from Rs 520',
      detail: '',
      icon: <CalendarDays size={18} />,
      tone: 'rose',
    },
  ];

  const tableRows = payments.length > 0 ? payments : fallbackPayments;
  const feedItems = activityFeed.length > 0 ? activityFeed : fallbackFeed;

  return (
    <div className="dashboard-page">
      <header className="dashboard-topbar">
        <a href="#/" className="dashboard-brand" aria-label="Back to home">
          <span className="dashboard-brand-mark" aria-hidden="true">
            V
          </span>
          <span className="dashboard-brand-name">Verity</span>
        </a>

        <nav className="dashboard-nav" aria-label="Primary">
          <a href="#/" className="active">
            Platform
          </a>
          <a href="#/dashboard">Solutions</a>
          <a href="#/dashboard">Integrations</a>
          <a href="#/dashboard">Company</a>
        </nav>

        <div className="dashboard-topbar-actions">
          <a href="#/dashboard" className="dashboard-secondary-action">
            Client Login
          </a>
          <a href="#/dashboard" className="dashboard-primary-action">
            Get Started
          </a>
        </div>
      </header>

      <div className="dashboard-shell">
        <aside className="dashboard-sidebar" aria-label="Sidebar navigation">
          <div className="dashboard-sidebar-group">
            <a href="#/dashboard" className="dashboard-sidebar-item active">
              <LayoutDashboard size={18} />
              <span>Dashboard</span>
              <span className="dashboard-sidebar-dot" aria-hidden="true" />
            </a>
            <button type="button" className="dashboard-sidebar-item">
              <Wallet size={18} />
              <span>Payments</span>
            </button>
            <button type="button" className="dashboard-sidebar-item">
              <RefreshCw size={18} />
              <span>Recoveries</span>
            </button>
            <button type="button" className="dashboard-sidebar-item">
              <Grid3x3 size={18} />
              <span>Audit Trail</span>
            </button>
            <button type="button" className="dashboard-sidebar-item">
              <Settings size={18} />
              <span>Settings</span>
            </button>
          </div>

          <button type="button" className="dashboard-sidebar-logout">
            <LogOut size={18} />
            <span>Logout</span>
          </button>
        </aside>

        <main className="dashboard-main">
          <section className="dashboard-hero">
            <div className="dashboard-hero-copy">
              <h1>Revenue Recovery Dashboard</h1>
              <p>Real-time recovery metrics and active operations.</p>
            </div>

            <div className="dashboard-hero-actions">
              <button type="button" className="dashboard-filter-button">
                <CalendarDays size={18} />
                <span>Last 7 Days</span>
                <ChevronDown size={16} />
              </button>
              <button type="button" className="dashboard-export-button">
                <ArrowUpRight size={18} />
                <span>Export Report</span>
              </button>
            </div>
          </section>

          <section className="dashboard-metrics" aria-busy={isLoading}>
            {cards.map((card, index) => (
              <motion.article
                key={card.label}
                className={`dashboard-metric-card dashboard-metric-${card.tone}`}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: index * 0.08 }}
              >
                <div className="dashboard-metric-head">
                  <div className="dashboard-metric-label">{card.label}</div>
                  <div className="dashboard-metric-icon" aria-hidden="true">
                    {card.icon}
                  </div>
                </div>
                <div className="dashboard-metric-value">{card.value}</div>
                <div className="dashboard-metric-foot">
                  {card.delta && <span>{card.delta}</span>}
                  {card.detail && <strong>{card.detail}</strong>}
                </div>
              </motion.article>
            ))}
          </section>

          <section className="dashboard-table-panel">
            <div className="dashboard-section-head">
              <h2>Active Recoveries</h2>
            </div>

            {error && <div className="dashboard-banner">{error}</div>}

            <div className="dashboard-table-wrap">
              <table className="dashboard-table">
                <thead>
                  <tr>
                    <th>Payment ID</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Strategy</th>
                    <th>Money Recovered</th>
                    <th>Last Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((payment, index) => (
                    <motion.tr
                      key={payment.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25, delay: index * 0.04 }}
                      onClick={() => openJourney(payment.id)}
                      className="dashboard-table-row"
                    >
                      <td className="dashboard-table-id">#{payment.id}</td>
                      <td>Rs {formatCurrency(payment.amount)}</td>
                      <td>
                        <span className={`dashboard-status dashboard-status-${payment.status}`}>
                          {statusLabel(payment.status)}
                        </span>
                      </td>
                      <td>{payment.strategyUsed.replace(/_/g, ' ')}</td>
                      <td>Rs {formatCurrency(payment.recoveredAmount)}</td>
                      <td>{payment.lastUpdated ?? 'Just now'}</td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </main>

        <aside className="dashboard-feed-panel" aria-label="Activity feed">
          <div className="dashboard-feed-head">
            <h2>Activity Feed</h2>
            <p>Live recovery events</p>
          </div>

          <div className="dashboard-feed-list">
            {feedItems.map((item, index) => (
              <motion.div
                key={`${item.paymentId}-${index}`}
                className="dashboard-feed-card"
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: index * 0.05 }}
              >
                <div className="dashboard-feed-icon" aria-hidden="true">
                  <MessageSquareText size={16} />
                </div>
                <div className="dashboard-feed-copy">
                  <strong>{item.label}</strong>
                  <span>{item.action}</span>
                  <em>{item.amount}</em>
                </div>
                <div className="dashboard-feed-time">{item.time}</div>
              </motion.div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default DashboardOverview;
