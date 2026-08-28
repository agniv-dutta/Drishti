import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  FileText,
  MessageSquareText,
  Mail,
  PartyPopper,
  Phone,
  RefreshCw,
  Smartphone,
} from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import type { DashboardJourneyNode } from '../types/dashboard';
import './DashboardPage.css';

const fallbackNodes: DashboardJourneyNode[] = [
  {
    id: 'created',
    title: 'Payment Initiated',
    subtitle: 'Payment Created',
    time: '2:15 PM',
    badge: 'Completed',
    badgeTone: 'sage',
    x: 7,
    y: 'above',
    circleTone: 'coral',
    completed: true,
    detail: 'The payment event was recorded and routed into the recovery pipeline.',
    status: 'created',
  },
  {
    id: 'declined',
    title: 'Declined by Bank',
    subtitle: 'Decline Detected',
    badge: 'Insufficient Funds',
    badgeTone: 'gray',
    x: 22,
    y: 'below',
    circleTone: 'rose',
    completed: true,
    reason: 'Failure reason',
    detail: 'Issuer returned a soft decline with no available balance at authorization time.',
  },
  {
    id: 'analysis',
    title: 'AI Analyzed',
    subtitle: 'AI Analysis',
    badge: '78% confidence',
    badgeTone: 'coral',
    x: 40,
    y: 'above',
    circleTone: 'coral',
    completed: true,
    detail: 'Recommended SMS outreach based on customer history and retry timing.',
    reasoning:
      'The model weighted previous SMS response rates, time-of-day behavior, and the low-friction payment link path.',
  },
  {
    id: 'sms',
    title: 'Customer Contacted',
    subtitle: 'SMS Sent',
    time: '2:45 PM',
    x: 58,
    y: 'below',
    circleTone: 'coral',
    completed: true,
    preview: 'Hi, payment failed. Retry now: [link]',
    detail: 'A personalized payment link was sent after the decline with a short retry prompt.',
  },
  {
    id: 'retried',
    title: 'Retry Successful',
    subtitle: 'Payment Retried',
    amount: '5000',
    x: 76,
    y: 'above',
    circleTone: 'coral',
    completed: true,
    detail: 'The customer retried the payment from the recovery link and the transaction cleared successfully.',
  },
  {
    id: 'complete',
    title: 'Revenue Recovered',
    subtitle: 'Recovery Complete',
    amount: '5000',
    x: 92,
    y: 'below',
    circleTone: 'gold',
    completed: true,
    current: true,
    detail: 'Recovery closed with a fully successful payment and a clean audit trail.',
  },
];

const iconMap: Record<string, React.ReactNode> = {
  created: <Check size={16} />,
  declined: <AlertTriangle size={16} />,
  analysis: <Bot size={16} />,
  sms: <Smartphone size={16} />,
  retried: <CheckCircle2 size={16} />,
  complete: <PartyPopper size={16} />,
};

const activityIconMap: Record<string, React.ReactNode> = {
  Envelope: <Mail size={16} />,
  Mail: <Mail size={16} />,
  Phone: <Phone size={16} />,
  RotateCcw: <RefreshCw size={16} />,
  ShieldAlert: <AlertTriangle size={16} />,
  Sparkles: <MessageSquareText size={16} />,
};

const formatCurrency = (value: number) =>
  new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 0,
  }).format(Math.round(value));

const DashboardPage: React.FC<{ paymentId?: string | null }> = ({ paymentId }) => {
  const loadDashboard = useDashboardStore((state) => state.loadDashboard);
  const selectPayment = useDashboardStore((state) => state.selectPayment);
  const journey = useDashboardStore((state) => state.journey);
  const payments = useDashboardStore((state) => state.payments);
  const recoveryRate = useDashboardStore((state) => state.recoveryRate);
  const targetRate = useDashboardStore((state) => state.targetRate);
  const totalRecovered = useDashboardStore((state) => state.totalRecovered);
  const totalPaymentsProcessed = useDashboardStore((state) => state.totalPaymentsProcessed);
  const activityFeed = useDashboardStore((state) => state.activityFeed);
  const selectedPaymentId = useDashboardStore((state) => state.selectedPaymentId);
  const isLoading = useDashboardStore((state) => state.isLoading);
  const error = useDashboardStore((state) => state.error);

  const [expandedId, setExpandedId] = useState<string | null>('analysis');
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  useEffect(() => {
    void loadDashboard(paymentId ?? undefined);
  }, [loadDashboard, paymentId]);

  const journeyNodes = journey?.nodes.length ? journey.nodes : fallbackNodes;
  const currentJourney = journey ?? null;
  const chargebackRisk = currentJourney?.chargebackRisk ?? null;
  const activeNode = useMemo(
    () => journeyNodes.find((node) => node.id === hoveredId) ?? null,
    [hoveredId, journeyNodes],
  );

  const linkSegments = useMemo(
    () =>
      journeyNodes.slice(0, -1).map((node, index) => {
        const next = journeyNodes[index + 1];
        const tone = index === 0 ? 'rose-dashed' : 'coral';
        return {
          id: `${node.id}-${next.id}`,
          left: node.x,
          width: Math.max(next.x - node.x, 8),
          tone,
        };
      }),
    [journeyNodes],
  );

  return (
    <div className="journey-page">
      <header className="journey-header">
        <a href="#/" className="journey-brand" aria-label="Back to Drishti home">
          <div className="journey-logo" aria-hidden="true">
            <span />
          </div>
          <span>Drishti</span>
        </a>

        <nav className="journey-nav" aria-label="Primary">
          <a href="#/dashboard/overview">Dashboard</a>
          <a href="#/dashboard/overview" className="active">
            Recovery Journey
          </a>
          <a href="#/page/integrations">Integrations</a>
          <a href="#/page/company">Company</a>
        </nav>

        <div className="journey-header-actions">
          <a href="#/page/client-login" className="journey-link-button">
            Client Login
          </a>
          <a href="#/page/get-started" className="journey-primary-button">
            Get Started
          </a>
        </div>
      </header>

      <main className="journey-main" aria-busy={isLoading}>
        <section className="journey-hero">
          <p className="journey-kicker">Single payment timeline</p>
          <h1>{currentJourney?.title ?? 'Recovery Journey'}</h1>
          <p className="journey-subtitle">
            {currentJourney?.subtitle ?? 'Transaction ID: #VR-8924-A'}
          </p>

          <div className="journey-summary-strip">
            <div className="journey-summary-chip">
              <span>Recovery rate</span>
              <strong>{recoveryRate.toFixed(0)}%</strong>
              <small>Target: {targetRate.toFixed(0)}%</small>
            </div>
            <div className="journey-summary-chip">
              <span>Total recovered</span>
              <strong>Rs {formatCurrency(totalRecovered)}</strong>
              <small>{totalPaymentsProcessed} processed</small>
            </div>
            <div className="journey-summary-chip">
              <span>Active recoveries</span>
              <strong>{payments.length}</strong>
              <small>{selectedPaymentId ? `Selected: ${selectedPaymentId.slice(-6)}` : 'No selection yet'}</small>
            </div>
          </div>
        </section>

        {chargebackRisk && (
          <section className={`chargeback-panel chargeback-panel-${chargebackRisk.riskBand}`}>
            <div className="chargeback-panel-head">
              <div>
                <p className="chargeback-kicker">Chargeback prevention</p>
                <h2>Predicted future chargeback risk</h2>
              </div>
              <div className="chargeback-score">
                <span>{chargebackRisk.riskScorePct.toFixed(1)}%</span>
                <small>{chargebackRisk.riskBand}</small>
              </div>
            </div>

            <div className="chargeback-grid">
              <div className="chargeback-item">
                <span>Customer history</span>
                <strong>{chargebackRisk.customerHistory.length ? chargebackRisk.customerHistory.join(' · ') : 'No prior risk flags'}</strong>
              </div>
              <div className="chargeback-item">
                <span>Product category</span>
                <strong>{chargebackRisk.productCategory}</strong>
              </div>
              <div className="chargeback-item">
                <span>Payment method</span>
                <strong>{chargebackRisk.paymentMethod}</strong>
              </div>
              <div className="chargeback-item">
                <span>Recovery path</span>
                <strong>{chargebackRisk.recoveryPath}</strong>
              </div>
            </div>

            <div className="chargeback-section">
              <h3>Recommended prevention actions</h3>
              <div className="chargeback-pills">
                {chargebackRisk.recommendedActions.map((action) => (
                  <span key={action}>{action}</span>
                ))}
              </div>
            </div>

            <div className="chargeback-section">
              <h3>Evidence to store</h3>
              <div className="chargeback-evidence">
                {chargebackRisk.evidenceToStore.map((item) => (
                  <span key={item}>
                    <FileText size={14} />
                    {item.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            </div>

            {chargebackRisk.manualReviewRequired && (
              <div className="chargeback-flag">
                Flag for manual review. The merchant team should monitor this payment closely.
              </div>
            )}
          </section>
        )}

        <section className="timeline-stage" aria-label="Payment recovery timeline">
          <div className="timeline-line timeline-line-base" aria-hidden="true" />

          {linkSegments.map((segment, index) => (
            <motion.div
              key={segment.id}
              className={`timeline-line timeline-line-${segment.tone}`}
              style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.5, delay: index * 0.1, ease: 'easeOut' }}
              aria-hidden="true"
            />
          ))}

          {journeyNodes.map((node, index) => {
            const isExpanded = expandedId === node.id;
            const connectorHeight = node.y === 'above' ? 72 : 76;
            const icon = iconMap[node.id] ?? <Check size={16} />;

            return (
              <motion.div
                key={node.id}
                className={`timeline-node timeline-node-${node.y}`}
                style={{ left: `${node.x}%` }}
                initial={{ opacity: 0, scale: 0.78, y: node.y === 'above' ? 14 : -14 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.3, delay: index * 0.1, ease: 'easeOut' }}
                onMouseEnter={() => setHoveredId(node.id)}
                onMouseLeave={() => setHoveredId(null)}
              >
                <div
                  className={`node-card node-card-${node.y} ${node.id === 'complete' ? 'node-card-gold' : ''}`}
                >
                  <div className="node-copy">
                    {node.time && <div className="node-time">{node.time}</div>}
                    <div className="node-title-row">
                      <div className={`node-title-dot node-tone-${node.circleTone}`} aria-hidden="true" />
                      <div className="node-title">{node.title}</div>
                    </div>
                    <div className="node-subtitle">{node.subtitle}</div>

                    {node.badge && (
                      <div className={`node-badge node-badge-${node.badgeTone ?? 'gray'}`}>{node.badge}</div>
                    )}

                    {node.preview && <div className="node-detail">{node.preview}</div>}
                    {node.amount && (
                      <div className={`node-amount ${node.id === 'complete' ? 'node-amount-gold' : ''}`}>
                        Rs {formatCurrency(Number(String(node.amount).replace(/,/g, '')))}
                      </div>
                    )}
                    {node.reason && <div className="node-reason">{node.reason}</div>}

                    {node.id === 'analysis' && (
                      <button
                        type="button"
                        className="node-expand"
                        onClick={() => setExpandedId((current) => (current === node.id ? null : node.id))}
                      >
                        {isExpanded ? 'Hide reasoning' : 'Show reasoning'}
                        <ChevronDown size={14} className={isExpanded ? 'expanded' : ''} />
                      </button>
                    )}

                    {node.id === 'analysis' && isExpanded && (
                      <div className="node-reasoning">{node.reasoning}</div>
                    )}

                    {node.detail && hoveredId === node.id && (
                      <motion.div
                        className={`node-tooltip ${node.y === 'above' ? 'tooltip-below' : 'tooltip-above'}`}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.18 }}
                      >
                        <strong>Details</strong>
                        <span>{node.detail}</span>
                      </motion.div>
                    )}
                  </div>
                </div>

                <div
                  className={`node-connector node-connector-${node.circleTone} ${node.id === 'declined' ? 'node-connector-dashed' : ''}`}
                  style={{ height: `${connectorHeight}px` }}
                  aria-hidden="true"
                />
                <div
                  className={`node-circle node-circle-${node.circleTone} ${node.current ? 'node-circle-current' : ''}`}
                >
                  {icon}
                </div>
              </motion.div>
            );
          })}

          <motion.div
            className="timeline-outcome"
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.35, delay: 0.7 }}
          >
            <div className="timeline-outcome-label">
              {currentJourney?.status === 'recovered' ? 'Revenue Recovered' : 'Recovery In Progress'}
            </div>
            <div className="timeline-outcome-amount">
              Rs {formatCurrency(currentJourney?.recoveredAmount ?? totalRecovered)}
            </div>
          </motion.div>

          {activeNode && (
            <motion.div
              className="timeline-floating-tip"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <strong>{activeNode.title}</strong>
              <span>{activeNode.detail ?? activeNode.subtitle}</span>
            </motion.div>
          )}

          {activityFeed.length > 0 && (
            <div className="timeline-activity-rail">
              {activityFeed.map((item) => (
                <button
                  type="button"
                  key={item.paymentId}
                  className="timeline-activity-chip"
                  onClick={() => void selectPayment(item.paymentId)}
                >
                  <span className="timeline-activity-icon">{activityIconMap[item.icon] ?? <MessageSquareText size={16} />}</span>
                  <span className="timeline-activity-copy">
                    <strong>{item.label}</strong>
                    <span>
                      {item.action} {item.amount}
                    </span>
                  </span>
                  <span className="timeline-activity-time">{item.time}</span>
                </button>
              ))}
            </div>
          )}

          {error && <div className="timeline-error">{error}</div>}
        </section>
      </main>

      <footer className="journey-footer">
        <div className="journey-footer-brand">Drishti</div>
        <div className="journey-footer-copy">© 2024 Drishti Revenue Recovery. All rights reserved.</div>
        <div className="journey-footer-links">
          <a href="#">Privacy Policy</a>
          <a href="#">Terms of Service</a>
          <a href="#">Security</a>
          <a href="#">Contact</a>
        </div>
      </footer>
    </div>
  );
};

export default DashboardPage;
