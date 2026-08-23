import React, { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  PartyPopper,
  Smartphone,
} from 'lucide-react';
import './DashboardPage.css';

type JourneyNode = {
  id: string;
  title: string;
  subtitle: string;
  time?: string;
  status?: string;
  detail?: string;
  badge?: string;
  badgeTone?: 'gray' | 'sage' | 'coral' | 'rose' | 'gold';
  x: number;
  y: 'above' | 'below';
  circleTone: 'coral' | 'rose' | 'gold';
  icon: React.ReactNode;
  completed: boolean;
  current?: boolean;
  reason?: string;
  amount?: string;
  preview?: string;
  emphasis?: string;
  reasoning?: string;
};

const journeyNodes: JourneyNode[] = [
  {
    id: 'created',
    title: 'Payment Initiated',
    subtitle: 'Payment Created',
    time: '2:15 PM',
    status: 'Completed',
    badge: 'Completed',
    badgeTone: 'sage',
    x: 7,
    y: 'above',
    circleTone: 'coral',
    icon: <Check size={16} />,
    completed: true,
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
    icon: <AlertTriangle size={16} />,
    completed: true,
    reason: 'Failure reason',
    detail: 'Issuer returned a soft decline from the bank with no available balance at authorization time.',
  },
  {
    id: 'analysis',
    title: 'AI Analyzed',
    subtitle: 'AI Analysis',
    x: 40,
    y: 'above',
    circleTone: 'coral',
    icon: <Bot size={16} />,
    completed: true,
    detail: 'Recommended SMS outreach with a 78% confidence score based on customer history and retry timing.',
    reasoning:
      'The model weighted previous SMS response rates, time-of-day behavior, and the low friction path to a payment link. It rejected call-first recovery because the customer had a stronger SMS completion history.',
  },
  {
    id: 'sms',
    title: 'Customer Contacted',
    subtitle: 'SMS Sent',
    time: '2:45 PM',
    x: 58,
    y: 'below',
    circleTone: 'coral',
    icon: <Smartphone size={16} />,
    completed: true,
    preview: 'Hi, payment failed. Retry now: [link]',
    detail: 'A personalized payment link was sent after the decline with a short retry prompt.',
  },
  {
    id: 'retried',
    title: 'Retry Successful',
    subtitle: 'Payment Retried',
    amount: '₹5,000',
    x: 76,
    y: 'above',
    circleTone: 'coral',
    icon: <CheckCircle2 size={16} />,
    completed: true,
    detail: 'The customer retried the payment from the SMS link and the transaction cleared successfully.',
  },
  {
    id: 'complete',
    title: 'Revenue Recovered',
    subtitle: 'Recovery Complete',
    amount: '₹5,000',
    x: 92,
    y: 'below',
    circleTone: 'gold',
    icon: <PartyPopper size={16} />,
    completed: true,
    current: true,
    detail: 'Recovery closed with a fully successful payment and a clean audit trail.',
  },
];

const linkSegments = [
  { id: 'seg-1', left: 7, width: 15, tone: 'rose-dashed' },
  { id: 'seg-2', left: 22, width: 18, tone: 'coral' },
  { id: 'seg-3', left: 40, width: 18, tone: 'coral' },
  { id: 'seg-4', left: 58, width: 18, tone: 'coral' },
  { id: 'seg-5', left: 76, width: 16, tone: 'coral' },
];

const DashboardPage: React.FC = () => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>('analysis');

  const activeNode = useMemo(
    () => journeyNodes.find((node) => node.id === hoveredId) ?? null,
    [hoveredId],
  );

  return (
    <div className="journey-page">
      <header className="journey-header">
        <div className="journey-brand">
          <div className="journey-logo" aria-hidden="true">
            <span />
          </div>
          <span>Verity</span>
        </div>

        <nav className="journey-nav" aria-label="Primary">
          <a href="#">Platform</a>
          <a href="#" className="active">
            Solutions
          </a>
          <a href="#">Integrations</a>
          <a href="#">Company</a>
        </nav>

        <div className="journey-header-actions">
          <a href="#" className="journey-link-button">
            Client Login
          </a>
          <a href="#" className="journey-primary-button">
            Get Started
          </a>
        </div>
      </header>

      <main className="journey-main">
        <section className="journey-hero">
          <p className="journey-kicker">Single payment timeline</p>
          <h1>Recovery Journey</h1>
          <p className="journey-subtitle">Transaction ID: #VR-8924-A</p>
        </section>

        <section className="timeline-stage" aria-label="Payment recovery timeline">
          <div className="timeline-line timeline-line-base" aria-hidden="true" />

          {linkSegments.map((segment, index) => (
            <motion.div
              key={segment.id}
              className={`timeline-line timeline-line-${segment.tone}`}
              style={{
                left: `${segment.left}%`,
                width: `${segment.width}%`,
              }}
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.5, delay: index * 0.1, ease: 'easeOut' }}
              aria-hidden="true"
            />
          ))}

          {journeyNodes.map((node, index) => {
            const isHovered = hoveredId === node.id;
            const isExpanded = expandedId === node.id;
            const connectorHeight = node.y === 'above' ? 72 : 76;

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
                        {node.amount}
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
                      <div className="node-reasoning">
                        {node.reasoning}
                      </div>
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
                <div className={`node-circle node-circle-${node.circleTone} ${node.current ? 'node-circle-current' : ''}`}>
                  {node.icon}
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
            <div className="timeline-outcome-label">Revenue Recovered</div>
            <div className="timeline-outcome-amount">₹5,000</div>
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
        </section>
      </main>

      <footer className="journey-footer">
        <div className="journey-footer-brand">Verity</div>
        <div className="journey-footer-copy">© 2024 Verity Revenue Recovery. All rights reserved.</div>
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
