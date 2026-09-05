import React, { useEffect, useState, useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  BadgePercent,
  Brain,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Grid3x3,
  LayoutDashboard,
  LogOut,
  Mail,
  MessageSquareText,
  Phone,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  TrendingDown,
  Wallet,
} from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import type { DashboardActivityItem, Payment } from '../types/dashboard';

import './DashboardOverview.css';

export type DashboardSection = 'overview' | 'payments' | 'recoveries' | 'receivables' | 'subscriptions' | 'analytics' | 'workflows' | 'audit-trail' | 'agent-operations' | 'settings';

type DashboardOverviewProps = {
  section: DashboardSection;
};

const settingsRows = [
  { label: 'Auto-retry window', value: '5 minutes' },
  { label: 'SMS fallback', value: 'Enabled' },
  { label: 'Voice escalation', value: 'Enabled' },
  { label: 'Audit logging', value: 'Immutable' },
];

const formatCurrency = (value: number) =>
  new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(Math.round(value));

const statusLabel = (status: Payment['status']) =>
  status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ');

const sectionLabel: Record<DashboardSection, string> = {
  overview: 'Dashboard',
  payments: 'Payments',
  recoveries: 'Recoveries',
  receivables: 'Receivables',
  subscriptions: 'Subscriptions',
  analytics: 'Analytics',
  workflows: 'Workflows',
  'audit-trail': 'Audit Trail',
  'agent-operations': 'Agent Operations',
  settings: 'Settings',
};

type AgentStage = {
  id: string;
  name: string;
  icon: React.ReactNode;
  count: number;
  percentage: number;
  topFinding: string;
  details: string;
};

type AgentReasoning = {
  paymentId: string;
  confidence: number;
  reasoning: string;
  strategy: string;
  auditTrail: string[];
};

type DetailedAuditEvent = {
  id: string;
  eventNumber: number;
  title: string;
  timestamp: string;
  paymentId: string;
  amount: number;
  analyzer: {
    finding: string;
    confidence: number;
  };
  strategist: {
    recommendations: Array<{ strategy: string; successRate: number }>;
    chosen: string;
    reason: string;
  };
  supervisor: {
    gates: Array<{ check: string; passed: boolean }>;
    approved: boolean;
  };
  outcome: string;
  outcomeStatus: 'pending' | 'success' | 'failed';
};

type RecoveryRow = {
  paymentId: string;
  amount: number;
  status: 'RECOVERED' | 'FAILED' | 'ESCALATED';
  strategy: string;
  confidence: number;
  reason: string;
  modelPrediction: {
    recoveryProbability: number;
    predictedOutcome: string;
    actualOutcome: string;
    predictionCorrect: boolean;
    modelLearning: string;
  };
};

type ConfidenceLevel = 'high' | 'medium' | 'low';

const getConfidenceLevel = (confidence: number): ConfidenceLevel => {
  if (confidence >= 80) return 'high';
  if (confidence >= 60) return 'medium';
  return 'low';
};

const ConfidenceBadge: React.FC<{ confidence: number; showLabel?: boolean }> = ({ confidence, showLabel = false }) => {
  const level = getConfidenceLevel(confidence);
  return (
    <span className={`confidence-badge ${level}`}>
      <Brain size={10} />
      {showLabel && <span>{confidence}%</span>}
      {!showLabel && <span>{confidence}%</span>}
    </span>
  );
};

type MetricCard = {
  label: string;
  value: string | number;
  delta: string;
  detail: string;
  icon: React.ReactNode;
  tone: string;
  breakdown?: { label: string; value: string }[];
  trend?: 'up' | 'down' | 'neutral';
  isModelHealth?: boolean;
};

type ModelHealthMetrics = {
  strategyAccuracy: number;
  predictionF1: number;
  confidenceCalibration: number;
  lastTrained: string;
  nextRetrain: string;
  driftDetected: number;
  driftAlert: string;
};

type AgentDecision = {
  agent: string;
  type: 'parallel' | 'sequence';
  timestamp: string;
  steps: Array<{
    label: string;
    value: string;
    confidence?: number;
    status?: 'success' | 'pending' | 'warning';
  }>;
  next?: string;
};

type PaymentJourney = {
  paymentId: string;
  amount: number;
  initialStatus: string;
  agents: AgentDecision[];
  execution: {
    timestamp: string;
    action: string;
  };
};

type ABTest = {
  testName: string;
  control: {
    description: string;
    sent: number;
    recovered: number;
    rate: number;
  };
  variant: {
    description: string;
    sent: number;
    recovered: number;
    rate: number;
    isWinner: boolean;
  };
  improvement: string;
  reason: string;
  status: string;
};

type AgentActivity = {
  name: string;
  capacity: number;
  current: number;
  activity: string;
  currentTask: string;
  queueDepth: number;
};

const AnimatedCounter: React.FC<{ value: number; suffix?: string; duration?: number }> = ({ value, suffix = '', duration = 2000 }) => {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true });

  useEffect(() => {
    if (!isInView) return;
    let startTime: number;
    let animationFrame: number;

    const animate = (currentTime: number) => {
      if (!startTime) startTime = currentTime;
      const progress = Math.min((currentTime - startTime) / duration, 1);
      const easeOutQuart = 1 - Math.pow(1 - progress, 4);
      setCount(Math.floor(easeOutQuart * value));

      if (progress < 1) {
        animationFrame = requestAnimationFrame(animate);
      }
    };

    animationFrame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationFrame);
  }, [isInView, value, duration]);

  return (
    <span ref={ref}>
      {count.toLocaleString('en-IN')}{suffix}
    </span>
  );
};

const DashboardOverview: React.FC<DashboardOverviewProps> = ({ section }) => {
  const loadDashboard = useDashboardStore((state) => state.loadDashboard);
  const isLoading = useDashboardStore((state) => state.isLoading);
  const error = useDashboardStore((state) => state.error);
  const recoveryRate = useDashboardStore((state) => state.recoveryRate);
  const targetRate = useDashboardStore((state) => state.targetRate);
  const totalRecovered = useDashboardStore((state) => state.totalRecovered);
  const totalPaymentsProcessed = useDashboardStore((state) => state.totalPaymentsProcessed);
  const payments = useDashboardStore((state) => state.payments);
  const activityFeed = useDashboardStore((state) => state.activityFeed);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const periodDays = useDashboardStore((state) => state.periodDays);
  const setPeriod = useDashboardStore((state) => state.setPeriod);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
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

  const agentStages: AgentStage[] = [
    {
      id: 'analyzer',
      name: 'PaymentAnalyzer',
      icon: <Search size={16} />,
      count: 856,
      percentage: 68,
      topFinding: '34% insufficient_funds, 22% declined_by_issuer',
      details: 'Analyzing payment failure patterns and issuer responses',
    },
    {
      id: 'selector',
      name: 'StrategySelector',
      icon: <Brain size={16} />,
      count: 638,
      percentage: 51,
      topFinding: 'SMS (42%), Retry (35%), Call (18%), Offer (5%)',
      details: 'Selecting optimal recovery strategies based on ML models',
    },
    {
      id: 'orchestrator',
      name: 'ExecutionOrchestrator',
      icon: <RefreshCw size={16} />,
      count: 412,
      percentage: 33,
      topFinding: 'Success rate: 58% (240 recovered)',
      details: 'Executing recovery actions across multiple channels',
    },
    {
      id: 'supervisor',
      name: 'AuditSupervisor',
      icon: <ShieldCheck size={16} />,
      count: 412,
      percentage: 100,
      topFinding: 'All actions logged for compliance',
      details: 'Monitoring and logging all agent activities',
    },
  ];

  const agentReasoningData: Record<string, AgentReasoning[]> = {
    analyzer: [
      { paymentId: 'VR-8921', confidence: 78, reasoning: 'Insufficient funds detected with 78% confidence based on issuer response code', strategy: 'SMS', auditTrail: ['Payment failed at 14:32', 'Analysis started at 14:33', 'Insufficient funds identified'] },
      { paymentId: 'VR-8910', confidence: 85, reasoning: 'Declined by issuer - customer has previous successful payments', strategy: 'Retry', auditTrail: ['Payment failed at 13:15', 'Analysis completed at 13:16', 'Retry recommended'] },
      { paymentId: 'VR-8854', confidence: 62, reasoning: 'Technical error - possible network timeout', strategy: 'Retry', auditTrail: ['Payment failed at 12:45', 'Network timeout detected', 'Retry suggested'] },
      { paymentId: 'VR-8848', confidence: 91, reasoning: 'Card expired - requires customer intervention', strategy: 'Call', auditTrail: ['Payment failed at 11:20', 'Card expiry confirmed', 'Call escalation needed'] },
      { paymentId: 'VR-8832', confidence: 74, reasoning: 'Suspicious activity pattern detected', strategy: 'Offer', auditTrail: ['Payment failed at 10:05', 'Risk flag raised', 'Offer with verification'] },
    ],
    selector: [
      { paymentId: 'VR-8921', confidence: 82, reasoning: 'Customer responds well to SMS based on history (78% success rate)', strategy: 'SMS', auditTrail: ['Strategy selected at 14:34', 'SMS template chosen', 'Scheduled for delivery'] },
      { paymentId: 'VR-8910', confidence: 79, reasoning: 'Retry window available - issuer allows immediate retry', strategy: 'Retry', auditTrail: ['Retry approved at 13:17', 'Payment queued', 'Executing retry'] },
      { paymentId: 'VR-8854', confidence: 88, reasoning: 'Technical issues resolve with retry - 85% historical success', strategy: 'Retry', auditTrail: ['Retry strategy chosen at 12:47', 'Technical retry initiated', 'Monitoring progress'] },
      { paymentId: 'VR-8848', confidence: 95, reasoning: 'Card expiry requires human intervention - call necessary', strategy: 'Call', auditTrail: ['Call strategy selected at 11:22', 'Agent assigned', 'Call initiated'] },
      { paymentId: 'VR-8832', confidence: 71, reasoning: 'Risk mitigation needed - offer with verification reduces chargeback risk', strategy: 'Offer', auditTrail: ['Offer strategy chosen at 10:07', 'Verification flow added', 'Offer prepared'] },
    ],
    orchestrator: [
      { paymentId: 'VR-8921', confidence: 85, reasoning: 'SMS delivered successfully - awaiting customer response', strategy: 'SMS', auditTrail: ['SMS sent at 14:35', 'Delivery confirmed', 'Response pending'] },
      { paymentId: 'VR-8910', confidence: 92, reasoning: 'Retry executed successfully - payment recovered', strategy: 'Retry', auditTrail: ['Retry executed at 13:18', 'Payment successful', 'Amount recovered'] },
      { paymentId: 'VR-8854', confidence: 68, reasoning: 'Retry in progress - monitoring for completion', strategy: 'Retry', auditTrail: ['Retry started at 12:48', 'Processing', 'Awaiting result'] },
      { paymentId: 'VR-8848', confidence: 89, reasoning: 'Call connected - agent negotiating with customer', strategy: 'Call', auditTrail: ['Call connected at 11:25', 'Agent active', 'Negotiation in progress'] },
      { paymentId: 'VR-8832', confidence: 76, reasoning: 'Offer presented - customer considering options', strategy: 'Offer', auditTrail: ['Offer sent at 10:08', 'Customer viewing', 'Decision pending'] },
    ],
    supervisor: [
      { paymentId: 'VR-8921', confidence: 100, reasoning: 'All actions logged - compliant with audit requirements', strategy: 'SMS', auditTrail: ['Analysis logged', 'Strategy selection logged', 'Execution logged'] },
      { paymentId: 'VR-8910', confidence: 100, reasoning: 'Complete audit trail maintained for successful recovery', strategy: 'Retry', auditTrail: ['Failure logged', 'Retry logged', 'Success logged'] },
      { paymentId: 'VR-8854', confidence: 100, reasoning: 'Real-time monitoring active - all steps recorded', strategy: 'Retry', auditTrail: ['Detection logged', 'Strategy logged', 'Execution logged'] },
      { paymentId: 'VR-8848', confidence: 100, reasoning: 'Human intervention documented - full compliance maintained', strategy: 'Call', auditTrail: ['Risk logged', 'Escalation logged', 'Call logged'] },
      { paymentId: 'VR-8832', confidence: 100, reasoning: 'Risk mitigation documented - audit trail complete', strategy: 'Offer', auditTrail: ['Risk logged', 'Offer logged', 'Verification logged'] },
    ],
  };

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard, periodDays]);

  const openJourney = (paymentId: string) => {
    setSelectedPaymentJourney(paymentId);
  };

  const tableRows = payments;
  const feedItems = activityFeed;
  const activeFeedIcon = (icon: DashboardActivityItem['icon']) => {
    switch (icon) {
      case 'Phone':
        return <Phone size={16} />;
      case 'Mail':
        return <Mail size={16} />;
      default:
        return <MessageSquareText size={16} />;
    }
  };

  const [expandedCard, setExpandedCard] = useState<string | null>(null);
  const [expandedAuditEvent, setExpandedAuditEvent] = useState<string | null>(null);
  const [selectedConfidence, setSelectedConfidence] = useState<string | null>(null);
  const [selectedPaymentJourney, setSelectedPaymentJourney] = useState<string | null>(null);

  const modelHealth: ModelHealthMetrics = {
    strategyAccuracy: 84,
    predictionF1: 0.87,
    confidenceCalibration: 0.91,
    lastTrained: '2h ago',
    nextRetrain: '4h (automatic)',
    driftDetected: 12,
    driftAlert: 'retrain scheduled',
  };

  const paymentJourneys: Record<string, PaymentJourney> = {
    'VR-8910': {
      paymentId: 'VR-8910',
      amount: 85000,
      initialStatus: 'declined_by_issuer',
      agents: [
        {
          agent: 'PaymentAnalyzer',
          type: 'parallel',
          timestamp: 'T+0s',
          steps: [
            { label: 'Failure reason', value: 'declined_by_issuer' },
            { label: 'Confidence', value: '78%', confidence: 78 },
            { label: 'Root cause', value: 'Bank risk system flagged' },
            { label: 'Next', value: 'Send to strategist', status: 'success' },
          ],
          next: '✓',
        },
        {
          agent: 'StrategySelector',
          type: 'parallel',
          timestamp: 'T+0s',
          steps: [
            { label: 'Input', value: 'High-value (₹85K), business account' },
            { label: 'Option A', value: 'SMS (42% success)' },
            { label: 'Option B', value: 'Call (72% success) ← WINNER' },
            { label: 'Option C', value: 'Offer (18% success)' },
            { label: 'Chose', value: 'CALL with 72% confidence', confidence: 72 },
            { label: 'Reasoning', value: 'High-value needs personal touch' },
          ],
          next: '✓',
        },
        {
          agent: 'ExecutionOrchestrator',
          type: 'parallel',
          timestamp: 'T+0s',
          steps: [
            { label: 'Ready to execute', value: 'Voice call' },
            { label: 'Compliance check', value: 'Customer not opted out', status: 'success' },
            { label: '', value: 'Within daily limit (1/3 calls)', status: 'success' },
            { label: '', value: 'Within spend cap', status: 'success' },
            { label: 'Status', value: 'WAITING FOR SUPERVISOR APPROVAL', status: 'pending' },
            { label: 'Next', value: 'Run with supervisor gate' },
          ],
        },
        {
          agent: 'AuditSupervisor',
          type: 'sequence',
          timestamp: 'T+1s',
          steps: [
            { label: 'Reviewing', value: 'All agent decisions' },
            { label: 'Confidence levels', value: '78%, 72%, 94% (avg: 81%)' },
            { label: 'Gating decision', value: 'APPROVE (high confidence)', status: 'success' },
            { label: 'Logged to', value: 'audit trail' },
            { label: 'Execution', value: 'APPROVED', status: 'success' },
          ],
          next: '✓',
        },
      ],
      execution: {
        timestamp: 'T+5s',
        action: 'Call initiated to customer',
      },
    },
  };

  const aiImprovements: ABTest[] = [
    {
      testName: 'SMS timing optimization',
      control: {
        description: 'Send SMS immediately',
        sent: 2100,
        recovered: 640,
        rate: 30,
      },
      variant: {
        description: 'Send SMS at 9:15 PM',
        sent: 2050,
        recovered: 1230,
        rate: 60,
        isWinner: true,
      },
      improvement: '+100% recovery rate',
      reason: 'Peak response time for segment',
      status: 'Deployed to all users (T+2h)',
    },
  ];

  const agentActivities: AgentActivity[] = [
    {
      name: 'PaymentAnalyzer',
      capacity: 500,
      current: 420,
      activity: 'Analyzing failure reasons',
      currentTask: 'declined_by_issuer',
      queueDepth: 80,
    },
    {
      name: 'StrategySelector',
      capacity: 500,
      current: 380,
      activity: 'Recommending recovery strategies',
      currentTask: 'SMS (58% success)',
      queueDepth: 120,
    },
    {
      name: 'ExecutionOrchestrator',
      capacity: 500,
      current: 150,
      activity: 'Executing recovery workflows',
      currentTask: 'SMS send in progress',
      queueDepth: 350,
    },
    {
      name: 'AuditSupervisor',
      capacity: 500,
      current: 500,
      activity: 'Gating + logging all decisions',
      currentTask: '100% compliance',
      queueDepth: 0,
    },
  ];

  const recoveryRows: RecoveryRow[] = payments.map((payment, index) => {
    const status = payment.status.toUpperCase() as 'RECOVERED' | 'FAILED' | 'ESCALATED';
    const isRecovered = payment.recoveredAmount > 0;
    const confidence = isRecovered ? Math.min(95, 65 + payment.recoveredAmount / payment.amount * 35) : Math.round(40 + ((index * 13) % 40));
    const predicted = isRecovered ? 'Recovered' : 'Failed';
    return {
      paymentId: payment.id,
      amount: payment.amount,
      status: isRecovered ? 'RECOVERED' : payment.status === 'escalated' ? 'ESCALATED' : 'FAILED',
      strategy: payment.strategyUsed.replace(/_/g, ' '),
      confidence,
      reason: isRecovered
        ? 'AI recovery completed and amount collected'
        : payment.status === 'escalated'
          ? 'High-value account, human judgment needed'
          : 'AI confidence below threshold, escalated for review',
      modelPrediction: {
        recoveryProbability: Math.round(confidence),
        predictedOutcome: predicted,
        actualOutcome: isRecovered ? 'Recovered' : 'Failed',
        predictionCorrect: isRecovered ? predicted === 'Recovered' : predicted === 'Failed',
        modelLearning: isRecovered
          ? `Model validated: ${payment.strategyUsed.replace(/_/g, ' ')} strategy for this segment is performing well`
          : `Model adjusted: Recovery confidence for this segment updated based on latest outcomes`,
      },
    };
  });

  const detailedAuditEvents: DetailedAuditEvent[] = [
    {
      id: 'audit-1',
      eventNumber: 1,
      title: 'SMS sent to customer',
      timestamp: 'JUST NOW',
      paymentId: 'VR-8910',
      amount: 5000,
      analyzer: {
        finding: 'Insufficient funds',
        confidence: 78,
      },
      strategist: {
        recommendations: [
          { strategy: 'SMS', successRate: 82 },
          { strategy: 'Retry', successRate: 45 },
          { strategy: 'Call', successRate: 38 },
        ],
        chosen: 'SMS',
        reason: 'Highest success rate for this segment',
      },
      supervisor: {
        gates: [
          { check: 'Customer NOT opted out', passed: true },
          { check: 'Within daily contact limit (1/3)', passed: true },
          { check: 'Within daily spend cap', passed: true },
        ],
        approved: true,
      },
      outcome: 'Awaiting customer response',
      outcomeStatus: 'pending',
    },
    {
      id: 'audit-2',
      eventNumber: 2,
      title: 'Retry payment executed',
      timestamp: '2 MINS AGO',
      paymentId: 'VR-8921',
      amount: 12500,
      analyzer: {
        finding: 'Technical timeout',
        confidence: 62,
      },
      strategist: {
        recommendations: [
          { strategy: 'Retry', successRate: 85 },
          { strategy: 'SMS', successRate: 58 },
        ],
        chosen: 'Retry',
        reason: 'Technical issues resolve with retry',
      },
      supervisor: {
        gates: [
          { check: 'Retry window available', passed: true },
          { check: 'Issuer allows immediate retry', passed: true },
        ],
        approved: true,
      },
      outcome: 'Payment successful - amount recovered',
      outcomeStatus: 'success',
    },
    {
      id: 'audit-3',
      eventNumber: 3,
      title: 'Call escalation initiated',
      timestamp: '15 MINS AGO',
      paymentId: 'VR-8848',
      amount: 12850,
      analyzer: {
        finding: 'Card expired',
        confidence: 91,
      },
      strategist: {
        recommendations: [
          { strategy: 'Call', successRate: 72 },
          { strategy: 'Offer', successRate: 45 },
        ],
        chosen: 'Call',
        reason: 'Card expiry requires human intervention',
      },
      supervisor: {
        gates: [
          { check: 'Agent available', passed: true },
          { check: 'Customer contact hours', passed: true },
          { check: 'Risk threshold not exceeded', passed: true },
        ],
        approved: true,
      },
      outcome: 'Agent negotiating with customer',
      outcomeStatus: 'pending',
    },
  ];

  const cards: MetricCard[] = [
    {
      label: 'Total Payments Processed',
      value: totalPaymentsProcessed > 0 ? totalPaymentsProcessed : 1245,
      delta: '+12%',
      detail: 'This week',
      icon: <BadgePercent size={18} />,
      tone: 'coral',
      trend: 'up',
    },
    {
      label: 'Recovery Rate',
      value: recoveryRate > 0 ? recoveryRate : 58,
      delta: '',
      detail: `Target: ${(targetRate > 0 ? targetRate : 60).toFixed(0)}%`,
      icon: <RefreshCw size={18} />,
      tone: 'gold',
      trend: 'neutral',
    },
    {
      label: 'Money Recovered',
      value: totalRecovered > 0 ? totalRecovered : 4200000,
      delta: '+10.5%',
      detail: 'vs last week',
      icon: <Wallet size={18} />,
      tone: 'sand',
      trend: 'up',
      breakdown: [
        { label: 'Retry', value: '₹18L' },
        { label: 'SMS', value: '₹16L' },
        { label: 'Call', value: '₹8L' },
      ],
    },
    {
      label: 'AI Model Performance',
      value: modelHealth.strategyAccuracy,
      delta: `${modelHealth.predictionF1.toFixed(2)} F1`,
      detail: 'Strategy Selection Accuracy',
      icon: <Brain size={18} />,
      tone: 'gold',
      trend: 'up',
      isModelHealth: true,
    },
    {
      label: 'Avg Cost per Recovery',
      value: totalRecovered > 0 ? Math.round(totalRecovered * 0.015) : 0,
      delta: '',
      detail: 'Calculated from completed recoveries',
      icon: <Activity size={18} />,
      tone: 'sage',
      trend: 'neutral',
    },
  ];
  const chargebackRows = tableRows
    .filter((payment) => payment.chargebackRisk)
    .sort((a, b) => (b.chargebackRisk?.riskScorePct ?? 0) - (a.chargebackRisk?.riskScorePct ?? 0));
  const chargebackWatch = chargebackRows.filter((payment) => (payment.chargebackRisk?.riskScorePct ?? 0) > 40);
  const topChargeback = chargebackRows[0] ?? null;
  const averageChargebackRisk = chargebackRows.length
    ? chargebackRows.reduce((sum, payment) => sum + (payment.chargebackRisk?.riskScorePct ?? 0), 0) / chargebackRows.length
    : 0;
  const manualReviewCount = chargebackRows.filter((payment) => payment.chargebackRisk?.manualReviewRequired).length;

  return (
    <div className="dashboard-page">
      <header className="dashboard-topbar">
        <a href="#/" className="dashboard-brand" aria-label="Back to home">
          <span className="dashboard-brand-mark" aria-hidden="true">
            D
          </span>
          <span className="dashboard-brand-name">Drishti</span>
        </a>

        <nav className="dashboard-nav" aria-label="Primary">
          <a href="#/page/platform" className="dashboard-nav-link">
            Platform
          </a>
          <a href="#/page/solutions" className="dashboard-nav-link">
            Solutions
          </a>
          <a href="#/page/integrations" className="dashboard-nav-link">
            Integrations
          </a>
          <a href="#/page/company" className="dashboard-nav-link">
            Company
          </a>
        </nav>

        <div className="dashboard-topbar-actions">
          <a href="#/page/client-login" className="dashboard-secondary-action">
            Client Login
          </a>
          <a href="#/page/get-started" className="dashboard-primary-action">
            Get Started
          </a>
        </div>
      </header>

      <div className={`dashboard-shell ${sidebarOpen ? 'sidebar-open' : 'sidebar-collapsed'}`}>
        <aside className="dashboard-sidebar" aria-label="Sidebar navigation">
          <div className="dashboard-sidebar-group">
            <a href="#/dashboard/overview" className={`dashboard-sidebar-item ${section === 'overview' ? 'active' : ''}`}>
              <LayoutDashboard size={18} />
              <span className="dashboard-sidebar-text">Dashboard</span>
              {section === 'overview' && <span className="dashboard-sidebar-dot" aria-hidden="true" />}
            </a>
            <a href="#/dashboard/payments" className={`dashboard-sidebar-item ${section === 'payments' ? 'active' : ''}`}>
              <Wallet size={18} />
              <span className="dashboard-sidebar-text">Payments</span>
            </a>
            <a href="#/dashboard/recoveries" className={`dashboard-sidebar-item ${section === 'recoveries' ? 'active' : ''}`}>
              <RefreshCw size={18} />
              <span className="dashboard-sidebar-text">Recoveries</span>
            </a>
            <a href="#/receivables" className={`dashboard-sidebar-item ${section === 'receivables' ? 'active' : ''}`}>
              <Wallet size={18} />
              <span className="dashboard-sidebar-text">Receivables</span>
            </a>
            <a href="#/subscriptions" className={`dashboard-sidebar-item ${section === 'subscriptions' ? 'active' : ''}`}>
              <RefreshCw size={18} />
              <span className="dashboard-sidebar-text">Subscriptions</span>
            </a>
            <a href="#/dashboard/analytics" className={`dashboard-sidebar-item ${section === 'analytics' ? 'active' : ''}`}>
              <Grid3x3 size={18} />
              <span className="dashboard-sidebar-text">Analytics</span>
            </a>
            <a href="#/dashboard/workflows" className={`dashboard-sidebar-item ${section === 'workflows' ? 'active' : ''}`}>
              <Grid3x3 size={18} />
              <span className="dashboard-sidebar-text">Workflows</span>
            </a>
            <a href="#/dashboard/audit-trail" className={`dashboard-sidebar-item ${section === 'audit-trail' ? 'active' : ''}`}>
              <Grid3x3 size={18} />
              <span className="dashboard-sidebar-text">Audit Trail</span>
            </a>
            <a href="#/dashboard/agent-operations" className={`dashboard-sidebar-item ${section === 'agent-operations' ? 'active' : ''}`}>
              <RefreshCw size={18} />
              <span className="dashboard-sidebar-text">Agent Operations</span>
            </a>
            <a href="#/dashboard/settings" className={`dashboard-sidebar-item ${section === 'settings' ? 'active' : ''}`}>
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
          <section className="dashboard-hero">
            <div className="dashboard-hero-copy">
              <h1>{section === 'overview' ? 'Revenue Recovery Dashboard' : sectionLabel[section]}</h1>
              <p>{section === 'overview' ? 'Real-time recovery metrics and active operations.' : `Manage ${sectionLabel[section].toLowerCase()} from one place.`}</p>
            </div>

            <div className="dashboard-hero-actions">
              <div className="dashboard-filter-dropdown">
                <button type="button" className="dashboard-filter-button" onClick={() => setDropdownOpen(!dropdownOpen)}>
                  <CalendarDays size={18} />
                  <span>{periodDays === 7 ? 'Last 7 Days' : periodDays === 30 ? 'Last 30 Days' : `Last ${periodDays} Days`}</span>
                  <ChevronDown size={16} />
                </button>
                {dropdownOpen && (
                  <div className="dashboard-filter-menu">
                    <button type="button" onClick={() => { setPeriod(7); setDropdownOpen(false); }}>Last 7 Days</button>
                    <button type="button" onClick={() => { setPeriod(30); setDropdownOpen(false); }}>Last 30 Days</button>
                    <button type="button" onClick={() => { setPeriod(90); setDropdownOpen(false); }}>Last 90 Days</button>
                  </div>
                )}
              </div>
              <button type="button" className="dashboard-export-button" onClick={() => { window.location.hash = '#/dashboard/workflows'; }}>
                <ArrowUpRight size={18} />
                <span>{section === 'overview' ? 'Export Report' : 'Open Workspace'}</span>
              </button>
            </div>
          </section>

          {section === 'overview' && (
            <>
              <section className="dashboard-metrics" aria-busy={isLoading}>
                {cards.map((card, index) => (
                  <motion.article
                    key={card.label}
                    className={`dashboard-metric-card dashboard-metric-${card.tone} ${card.label === 'Money Recovered' ? 'metric-right-align' : ''} ${card.label === 'Avg Cost per Recovery' ? 'metric-centered' : ''}`}
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
                    <div className="dashboard-metric-value">
                      {card.isModelHealth ? (
                        <>
                          <AnimatedCounter value={card.value as number} suffix="%" duration={1500} />
                        </>
                      ) : typeof card.value === 'number' ? (
                        card.label === 'Recovery Rate' ? (
                          <AnimatedCounter value={card.value} suffix="%" duration={1500} />
                        ) : card.label === 'Money Recovered' ? (
                          <>₹<AnimatedCounter value={card.value} duration={2000} /></>
                        ) : card.label === 'Avg Cost per Recovery' ? (
                          <>₹<AnimatedCounter value={card.value} duration={1800} /></>
                        ) : (
                          <AnimatedCounter value={card.value} duration={2000} />
                        )
                      ) : (
                        card.value
                      )}
                    </div>
                    <div className="dashboard-metric-foot">
                      {card.trend === 'up' && card.delta && (
                        <span className="metric-trend-up">
                          <ArrowUp size={12} />
                          {card.delta}
                        </span>
                      )}
                      {card.trend === 'down' && card.delta && (
                        <span className="metric-trend-down">
                          <TrendingDown size={12} />
                          {card.delta}
                        </span>
                      )}
                      {card.trend === 'neutral' && card.delta && (
                        <span>{card.delta}</span>
                      )}
                      {card.detail && <strong>{card.detail}</strong>}
                    </div>
                    {card.breakdown && (
                      <div className="dashboard-metric-breakdown">
                        <button
                          type="button"
                          className="metric-breakdown-toggle"
                          onClick={() => setExpandedCard(expandedCard === card.label ? null : card.label)}
                        >
                          <span>View breakdown</span>
                          <ChevronRight
                            size={14}
                            className={`metric-chevron ${expandedCard === card.label ? 'expanded' : ''}`}
                          />
                        </button>
                        {expandedCard === card.label && (
                          <motion.div
                            className="metric-breakdown-content"
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            transition={{ duration: 0.2 }}
                          >
                            {card.breakdown.map((item) => (
                              <div key={item.label} className="metric-breakdown-item">
                                <span>{item.label}</span>
                                <strong>{item.value}</strong>
                              </div>
                            ))}
                          </motion.div>
                        )}
                      </div>
                    )}
                    {card.isModelHealth && (
                      <div className="dashboard-metric-breakdown">
                        <button
                          type="button"
                          className="metric-breakdown-toggle"
                          onClick={() => setExpandedCard(expandedCard === card.label ? null : card.label)}
                        >
                          <span>View model details</span>
                          <ChevronRight
                            size={14}
                            className={`metric-chevron ${expandedCard === card.label ? 'expanded' : ''}`}
                          />
                        </button>
                        {expandedCard === card.label && (
                          <motion.div
                            className="metric-breakdown-content model-health-content"
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            transition={{ duration: 0.2 }}
                          >
                            <div className="model-health-metric">
                              <span>Confidence Calibration</span>
                              <strong>{modelHealth.confidenceCalibration.toFixed(2)}</strong>
                            </div>
                            <div className="model-health-training">
                              <span>Last trained: <strong>{modelHealth.lastTrained}</strong></span>
                              <span>Next retrain: <strong>{modelHealth.nextRetrain}</strong></span>
                            </div>
                            {modelHealth.driftDetected > 0 && (
                              <div className="model-health-alert">
                                <span>⚠️ Drift detected: {modelHealth.driftDetected}%</span>
                                <span>({modelHealth.driftAlert})</span>
                              </div>
                            )}
                          </motion.div>
                        )}
                      </div>
                    )}
                  </motion.article>
                ))}
              </section>

              <section className="dashboard-agents-panel" aria-label="AI Agent Operations">
                <div className="dashboard-section-head">
                  <h2>AI Agents in Action</h2>
                  <span>Current batch: 1,245 payments being analyzed</span>
                </div>

                <div className="dashboard-agents-grid">
                  {agentStages.map((stage, index) => (
                    <motion.div
                      key={stage.id}
                      className="dashboard-agent-card"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: index * 0.1 }}
                    >
                      <button
                        type="button"
                        className="dashboard-agent-header"
                        onClick={() => setExpandedAgent(expandedAgent === stage.id ? null : stage.id)}
                      >
                        <div className="dashboard-agent-info">
                          <div className="dashboard-agent-icon">{stage.icon}</div>
                          <div className="dashboard-agent-details">
                            <strong>{stage.name}</strong>
                            <span>{stage.details}</span>
                          </div>
                        </div>
                        <div className="dashboard-agent-stats">
                          <span className="dashboard-agent-count">{stage.count}</span>
                          <span className="dashboard-agent-percentage">{stage.percentage}%</span>
                          <ChevronRight
                            size={16}
                            className={`dashboard-agent-chevron ${expandedAgent === stage.id ? 'expanded' : ''}`}
                          />
                        </div>
                      </button>
                      <div className="dashboard-agent-finding">
                        <em>Top finding:</em>
                        <span>{stage.topFinding}</span>
                      </div>
                      {expandedAgent === stage.id && (
                        <motion.div
                          className="dashboard-agent-reasoning"
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          transition={{ duration: 0.25 }}
                        >
                          <div className="dashboard-reasoning-header">
                            <strong>Sample Payment Reasoning</strong>
                            <span>Click payment to view full journey</span>
                          </div>
                          {agentReasoningData[stage.id]?.map((reasoning) => (
                            <div key={reasoning.paymentId} className="dashboard-reasoning-item">
                              <button
                                type="button"
                                className="dashboard-reasoning-payment"
                                onClick={() => openJourney(reasoning.paymentId)}
                              >
                                <span>#{reasoning.paymentId}</span>
                                <ConfidenceBadge confidence={reasoning.confidence} />
                              </button>
                              <div className="dashboard-reasoning-content">
                                <p>{reasoning.reasoning}</p>
                                <div className="dashboard-reasoning-meta">
                                  <span>Strategy: <strong>{reasoning.strategy}</strong></span>
                                </div>
                                <div className="dashboard-reasoning-audit">
                                  <span>Audit Trail:</span>
                                  {reasoning.auditTrail.map((trail, idx) => (
                                    <span key={idx}>{trail}</span>
                                  ))}
                                </div>
                              </div>
                            </div>
                          ))}
                        </motion.div>
                      )}
                    </motion.div>
                  ))}
                </div>
              </section>

              <section className="dashboard-ai-improvements-section" aria-label="AI Improvements This Week">
                <div className="dashboard-section-head">
                  <h2>AI Improvements This Week</h2>
                  <span>Automatic A/B testing and continuous learning</span>
                </div>

                <div className="ai-improvements-list">
                  {aiImprovements.map((test) => (
                    <div key={test.testName} className="ab-test-card">
                      <div className="ab-test-header">
                        <span>Test: {test.testName}</span>
                        {test.variant.isWinner && <span className="winner-badge">WINNING ✓</span>}
                      </div>

                      <div className="ab-test-comparison">
                        <div className="ab-test-group control">
                          <span className="ab-test-label">Control (old)</span>
                          <span className="ab-test-desc">{test.control.description}</span>
                          <div className="ab-test-results">
                            <span>{test.control.sent} SMS sent</span>
                            <span>→ {test.control.recovered} recoveries ({test.control.rate}%)</span>
                          </div>
                        </div>

                        <div className="ab-test-divider">
                          <span>vs</span>
                        </div>

                        <div className={`ab-test-group variant ${test.variant.isWinner ? 'winner' : ''}`}>
                          <span className="ab-test-label">Variant (AI)</span>
                          <span className="ab-test-desc">{test.variant.description}</span>
                          <div className="ab-test-results">
                            <span>{test.variant.sent} SMS sent</span>
                            <span>→ {test.variant.recovered} recoveries ({test.variant.rate}%)</span>
                          </div>
                        </div>
                      </div>

                      <div className="ab-test-improvement">
                        <span>Improvement: <strong>{test.improvement}</strong></span>
                        <span>Reason: "{test.reason}"</span>
                        <span>Status: {test.status}</span>
                      </div>

                      <div className="ab-test-footer">
                        <span>→ This is what AI learning looks like</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="dashboard-risk-strip" aria-label="Chargeback exposure summary">
                <div className="dashboard-risk-chip">
                  <span>Recovered at risk</span>
                  <strong>{chargebackRows.length}</strong>
                </div>
                <div className="dashboard-risk-chip">
                  <span>Average risk</span>
                  <strong>{averageChargebackRisk.toFixed(1)}%</strong>
                </div>
                <div className="dashboard-risk-chip">
                  <span>Manual reviews</span>
                  <strong>{manualReviewCount}</strong>
                </div>
              </section>

              <section className="dashboard-watch-panel" aria-label="Chargeback watch">
                <div className="dashboard-section-head dashboard-watch-head">
                  <h2>Chargeback Watch</h2>
                  <span>Recovered payments above the 40% threshold</span>
                </div>

                {!topChargeback ? (
                  <div className="dashboard-watch-empty">
                    No recovered payments are currently above the chargeback-risk threshold.
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      className="dashboard-watch-feature"
                      onClick={() => openJourney(topChargeback.id)}
                    >
                      <div className="dashboard-watch-feature-copy">
                        <div className="dashboard-watch-feature-topline">
                          <span className="dashboard-watch-feature-badge">Highest risk</span>
                          <span className="dashboard-watch-feature-score">
                            {topChargeback.chargebackRisk?.riskScorePct.toFixed(1)}%
                          </span>
                        </div>
                        <strong>#{topChargeback.id}</strong>
                        <p>
                          {topChargeback.chargebackRisk?.recommendedActions[0] ??
                            'Store extra evidence and keep the invoice ready for review.'}
                        </p>
                      </div>
                      <div className="dashboard-watch-feature-meta">
                        <span>{topChargeback.chargebackRisk?.riskBand ?? 'unknown'}</span>
                        <strong>{topChargeback.chargebackRisk?.recoveryPath ?? topChargeback.strategyUsed.replace(/_/g, ' ')}</strong>
                      </div>
                    </button>

                    {chargebackWatch.length > 0 && (
                      <div className="dashboard-watch-list">
                        {chargebackWatch.slice(0, 2).map((payment) => (
                          <button
                            key={payment.id}
                            type="button"
                            className="dashboard-watch-card"
                            onClick={() => openJourney(payment.id)}
                          >
                            <div className="dashboard-watch-copy">
                              <strong>#{payment.id}</strong>
                              <span>{payment.chargebackRisk?.recoveryPath ?? payment.strategyUsed.replace(/_/g, ' ')}</span>
                            </div>
                            <div className="dashboard-watch-risk">
                              <em>{payment.chargebackRisk?.riskBand ?? 'unknown'}</em>
                              <strong>{payment.chargebackRisk?.riskScorePct.toFixed(1) ?? '0.0'}%</strong>
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                )}
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
                        <th>Chargeback Risk</th>
                        <th>Last Updated</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tableRows.length === 0 ? (
                        <tr>
                          <td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>
                            No recovery data for this period. Ingest payments to get started.
                          </td>
                        </tr>
                      ) : tableRows.map((payment, index) => (
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
                          <td>
                            {payment.chargebackRisk ? (
                              <span className={`dashboard-risk-badge dashboard-risk-${payment.chargebackRisk.riskBand}`}>
                                {payment.chargebackRisk.riskScorePct.toFixed(1)}%
                              </span>
                            ) : (
                              <span className="dashboard-risk-badge dashboard-risk-none">None</span>
                            )}
                          </td>
                          <td>{payment.lastUpdated ?? 'Just now'}</td>
                        </motion.tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {section === 'payments' && (
            <section className="dashboard-payments-section">
              <div className="dashboard-section-head">
                <h2>AI-Powered Payments</h2>
                <span>AI strategy selection with confidence levels</span>
              </div>

              <div className="payments-list-container">
                {tableRows.slice(0, 5).map((payment) => {
                  const confidence = payment.recoveredAmount > 0 ? Math.min(95, 65 + payment.recoveredAmount / payment.amount * 35) : 58;
                  const strategy = payment.strategyUsed.replace(/_/g, ' ');
                  const reason = payment.recoveredAmount > 0
                    ? 'AI recovery completed and amount collected'
                    : payment.status === 'escalated'
                      ? 'High-value account, human judgment needed'
                      : 'AI confidence below threshold, escalation recommended';
                  
                  return (
                    <div key={payment.id} className="payment-card">
                      <button type="button" className="payment-card-main" onClick={() => openJourney(payment.id)}>
                        <div className="payment-card-header">
                          <span className="payment-id">#{payment.id}</span>
                          <span className="payment-amount">₹{payment.amount >= 1000 ? `${(payment.amount / 1000).toFixed(1)}K` : payment.amount}</span>
                        </div>
                        <div className="payment-card-status">
                          <span className={`status-badge ${payment.status.toLowerCase()}`}>
                            {statusLabel(payment.status)}
                          </span>
                        </div>
                      </button>
                      <div className="payment-card-ai">
                        <div className="payment-ai-info">
                          <span>Strategy: <strong>{strategy}</strong></span>
                          <ConfidenceBadge confidence={confidence} />
                        </div>
                        <span className="payment-ai-reason">{reason}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {section === 'recoveries' && (
            <section className="dashboard-recoveries-section">
              <div className="dashboard-section-head">
                <h2>AI-Powered Recoveries</h2>
                <span>Full transparency into AI decision-making and model learning</span>
              </div>

              <div className="recoveries-table-container">
                <table className="recoveries-table">
                  <thead>
                    <tr>
                      <th>Payment ID</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Strategy</th>
                      <th>Confidence</th>
                      <th>Why Escalated?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recoveryRows.length === 0 ? (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: 'rgba(247, 240, 234, 0.5)' }}>
                          No recovery data for this period. Ingest payments to get started.
                        </td>
                      </tr>
                    ) : recoveryRows.map((row) => (
                      <tr key={row.paymentId}>
                        <td><strong>#{row.paymentId}</strong></td>
                        <td>₹{row.amount >= 1000 ? `${(row.amount / 1000).toFixed(1)}K` : row.amount}</td>
                        <td>
                          <span className={`status-badge ${row.status.toLowerCase()}`}>
                            {row.status === 'RECOVERED' && 'RECOVERED'}
                            {row.status === 'FAILED' && 'FAILED'}
                            {row.status === 'ESCALATED' && 'ESCALATED'}
                          </span>
                        </td>
                        <td>{row.strategy}</td>
                        <td>
                          <button
                            type="button"
                            className="confidence-button"
                            onClick={() => setSelectedConfidence(selectedConfidence === row.paymentId ? null : row.paymentId)}
                          >
                            <ConfidenceBadge confidence={row.confidence} />
                          </button>
                        </td>
                        <td><span className="reason-text">{row.reason}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {selectedConfidence && (
                <div className="confidence-modal-overlay" onClick={() => setSelectedConfidence(null)}>
                  <motion.div
                    className="confidence-modal"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.2 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {(() => {
                      const row = recoveryRows.find((r) => r.paymentId === selectedConfidence);
                      if (!row) return null;
                      return (
                        <>
                          <div className="confidence-modal-header">
                            <div>
                              <span>Payment #{row.paymentId}</span>
                              <strong>Model Prediction Details</strong>
                            </div>
                            <button type="button" onClick={() => setSelectedConfidence(null)} className="modal-close">
                              ✕
                            </button>
                          </div>

                          <div className="confidence-modal-content">
                            <div className="prediction-section">
                              <h3>What Model Predicted</h3>
                              <div className="prediction-value">
                                <span>Recovery Probability</span>
                                <strong>{row.modelPrediction.recoveryProbability}%</strong>
                              </div>
                              <div className="prediction-outcome">
                                <span>Predicted Outcome</span>
                                <span className={`outcome-tag ${row.modelPrediction.predictedOutcome.toLowerCase()}`}>
                                  {row.modelPrediction.predictedOutcome}
                                </span>
                              </div>
                            </div>

                            <div className="prediction-section">
                              <h3>What Actually Happened</h3>
                              <div className="actual-outcome">
                                <span>Actual Outcome</span>
                                <span className={`outcome-tag ${row.modelPrediction.actualOutcome.toLowerCase()}`}>
                                  {row.modelPrediction.actualOutcome}
                                </span>
                              </div>
                              <div className={`prediction-accuracy ${row.modelPrediction.predictionCorrect ? 'correct' : 'incorrect'}`}>
                                <span>{row.modelPrediction.predictionCorrect ? '✅' : '❌'}</span>
                                <span>Prediction was {row.modelPrediction.predictionCorrect ? 'CORRECT' : 'INCORRECT'}</span>
                              </div>
                            </div>

                            <div className="prediction-section learning">
                              <h3><Brain size={16} />Model Learning</h3>
                              <p>{row.modelPrediction.modelLearning}</p>
                              {row.modelPrediction.predictionCorrect ? (
                                <span className="learning-badge validated">Model Validated</span>
                              ) : (
                                <span className="learning-badge updated">Model Updated</span>
                              )}
                            </div>
                          </div>
                        </>
                      );
                    })()}
                  </motion.div>
                </div>
              )}

              {selectedPaymentJourney && paymentJourneys[selectedPaymentJourney] && (
                <div className="journey-modal-overlay" onClick={() => setSelectedPaymentJourney(null)}>
                  <motion.div
                    className="journey-modal"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.2 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {(() => {
                      const journey = paymentJourneys[selectedPaymentJourney];
                      if (!journey) return null;
                      return (
                        <>
                          <div className="journey-modal-header">
                            <div>
                              <span>Payment #{journey.paymentId}</span>
                              <strong>Agent Decision Flow</strong>
                            </div>
                            <button type="button" onClick={() => setSelectedPaymentJourney(null)} className="modal-close">
                              ✕
                            </button>
                          </div>

                          <div className="journey-modal-content">
                            <div className="journey-initial">
                              <span>PAYMENT RECEIVED: ₹{journey.amount.toLocaleString('en-IN')} {journey.initialStatus}</span>
                              <span>↓ (T+0s)</span>
                            </div>

                            <div className="journey-agents">
                              {journey.agents.map((agent, idx) => (
                                <div key={idx} className={`journey-agent ${agent.type}`}>
                                  <div className="journey-agent-header">
                                    <span className="agent-type-badge">{agent.type}</span>
                                    <strong>{agent.agent}</strong>
                                    <span className="agent-timestamp">{agent.timestamp}</span>
                                  </div>
                                  <div className="journey-agent-steps">
                                    {agent.steps.map((step, stepIdx) => (
                                      <div key={stepIdx} className="journey-step">
                                        <span className="step-label">{step.label}</span>
                                        <span className="step-value">
                                          {step.confidence && <ConfidenceBadge confidence={step.confidence} />}
                                          {step.status === 'success' && <span className="step-status success">✓</span>}
                                          {step.status === 'pending' && <span className="step-status pending">⏳</span>}
                                          {step.value}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                  {agent.next && <div className="journey-agent-next">{agent.next}</div>}
                                </div>
                              ))}
                            </div>

                            <div className="journey-execution">
                              <span>EXECUTION ({journey.execution.timestamp})</span>
                              <strong>└─ {journey.execution.action}</strong>
                            </div>
                          </div>
                        </>
                      );
                    })()}
                  </motion.div>
                </div>
              )}
            </section>
          )}

          {section === 'agent-operations' && (
            <section className="agent-operations-section">
              <div className="dashboard-section-head">
                <div>
                  <p className="dashboard-eyebrow">Multi-agent orchestration</p>
                  <h2>Agent Collaboration</h2>
                  <p>How agents share signals, hand off decisions, and amplify each other's strengths.</p>
                </div>
              </div>

              <section className="dashboard-kpis">
                {[
                  { label: 'Synergy Score', value: '94%', detail: 'Cross-agent signal accuracy', icon: <Brain size={18} />, tone: 'gold' as const },
                  { label: 'Handoff Success', value: '97.2%', detail: 'Zero-loss context passing', icon: <ArrowUpRight size={18} />, tone: 'sage' as const },
                  { label: 'Avg Chain Depth', value: '3.1', detail: 'Agents per recovery decision', icon: <Activity size={18} />, tone: 'coral' as const },
                  { label: 'Conflict Rate', value: '0.4%', detail: 'Disagreements resolved automatically', icon: <ShieldCheck size={18} />, tone: 'rose' as const },
                ].map((card) => (
                  <motion.article
                    key={card.label}
                    className={`dashboard-kpi ${card.tone}`}
                    initial={{ opacity: 0, y: 18 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, amount: 0.2 }}
                    transition={{ duration: 0.45 }}
                  >
                    <div className="dashboard-kpi-head">
                      <span className="dashboard-kpi-label">{card.label}</span>
                      <span className="dashboard-kpi-icon">{card.icon}</span>
                    </div>
                    <div className="dashboard-kpi-body">
                      <strong>{card.value}</strong>
                      <small>{card.detail}</small>
                    </div>
                  </motion.article>
                ))}
              </section>

              <div className="agent-operations-header">
                <span>Agent Collaboration Matrix</span>
              </div>

              <div className="agent-mesh-grid">
                {agentActivities.map((agent) => (
                  <div key={agent.name} className="agent-mesh-card">
                    <div className="agent-mesh-card-head">
                      <strong>{agent.name}</strong>
                      <span className="agent-mesh-badge online">Online</span>
                    </div>
                    <div className="agent-mesh-card-body">
                      <p><strong>Primary role:</strong> {agent.activity}</p>
                      <p><strong>Current task:</strong> {agent.currentTask}</p>
                      <p><strong>Handoff partners:</strong> {agentActivities.filter((a) => a.name !== agent.name).slice(0, 2).map((a) => a.name).join(', ')}</p>
                    </div>
                    <div className="agent-mesh-card-footer">
                      <div className="agent-progress-bar">
                        <div className="agent-progress-fill" style={{ width: `${(agent.current / agent.capacity) * 100}%` }} />
                      </div>
                      <span>{agent.current}/{agent.capacity} slots</span>
                    </div>
                  </div>
                ))}
              </div>

              <div className="agent-mesh-status">
                <span>Communication backbone:</span>
                <div className="mesh-status-items">
                  <span className="mesh-status-item success">All agents sharing signals</span>
                  <span className="mesh-status-item success">Zero context loss in handoffs</span>
                  <span className="mesh-status-item success">Decision latency: 2.3s average</span>
                </div>
              </div>
            </section>
          )}

          {section === 'audit-trail' && (
            <section className="dashboard-audit-trail-section">
              <div className="dashboard-section-head">
                <h2>AI Decision Audit Trail</h2>
                <span>Full agent chain with reasoning and compliance gates</span>
              </div>
              
              <div className="audit-events-list">
                {detailedAuditEvents.map((event) => (
                  <div key={event.id} className="audit-event-card">
                    <button
                      type="button"
                      className="audit-event-header"
                      onClick={() => setExpandedAuditEvent(expandedAuditEvent === event.id ? null : event.id)}
                    >
                      <div className="audit-event-info">
                        <span className="audit-event-number">Event {event.eventNumber}</span>
                        <strong>{event.title}</strong>
                        <span className="audit-event-timestamp">{event.timestamp}</span>
                      </div>
                      <ChevronRight size={16} className={expandedAuditEvent === event.id ? 'expanded' : ''} />
                    </button>

                    {expandedAuditEvent === event.id && (
                      <motion.div
                        className="audit-event-details"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        transition={{ duration: 0.25 }}
                      >
                        <div className="audit-event-meta">
                          <div className="audit-meta-item">
                            <span>Payment ID:</span>
                            <strong>#{event.paymentId}</strong>
                          </div>
                          <div className="audit-meta-item">
                            <span>Amount:</span>
                            <strong>₹{event.amount.toLocaleString('en-IN')}</strong>
                          </div>
                        </div>

                        <div className="audit-agent-chain">
                          <div className="audit-agent-section analyzer">
                            <div className="audit-agent-header">
                              <Search size={16} />
                              <strong>Analyzer Finding</strong>
                              <span className="confidence-badge">{event.analyzer.confidence}% confidence</span>
                            </div>
                            <p>{event.analyzer.finding}</p>
                          </div>

                          <div className="audit-agent-section strategist">
                            <div className="audit-agent-header">
                              <Brain size={16} />
                              <strong>Strategist Recommendation</strong>
                            </div>
                            <div className="strategy-recommendations">
                              {event.strategist.recommendations.map((rec) => (
                                <div key={rec.strategy} className={`strategy-rec ${rec.strategy === event.strategist.chosen ? 'chosen' : ''}`}>
                                  <span>{rec.strategy}</span>
                                  <span>{rec.successRate}% success</span>
                                </div>
                              ))}
                            </div>
                            <div className="strategy-decision">
                              <span>→ Chose: <strong>{event.strategist.chosen}</strong></span>
                              <span>{event.strategist.reason}</span>
                            </div>
                          </div>

                          <div className="audit-agent-section supervisor">
                            <div className="audit-agent-header">
                              <ShieldCheck size={16} />
                              <strong>Supervisor Gates</strong>
                              <span className={`approval-status ${event.supervisor.approved ? 'approved' : 'rejected'}`}>
                                {event.supervisor.approved ? '✅ ACTION APPROVED' : '❌ ACTION REJECTED'}
                              </span>
                            </div>
                            <div className="supervisor-gates">
                              {event.supervisor.gates.map((gate, idx) => (
                                <div key={idx} className={`gate-item ${gate.passed ? 'passed' : 'failed'}`}>
                                  <span>{gate.passed ? '✅' : '❌'}</span>
                                  <span>{gate.check}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>

                        <div className="audit-outcome">
                          <span>Outcome (will update in 24h):</span>
                          <span className={`outcome-status ${event.outcomeStatus}`}>
                            {event.outcomeStatus === 'pending' && '⏳'}
                            {event.outcomeStatus === 'success' && '✅'}
                            {event.outcomeStatus === 'failed' && '❌'}
                            {event.outcome}
                          </span>
                        </div>

                        <button type="button" className="audit-download-pdf">
                          <Download size={14} />
                          Download detailed reasoning as PDF
                        </button>
                      </motion.div>
                    )}
                  </div>
                ))}
              </div>

              <div className="audit-compliance-info">
                <div className="compliance-card">
                  <ShieldCheck size={20} />
                  <div>
                    <strong>Compliance Ready</strong>
                    <span>Full decision tree available for regulatory audits</span>
                  </div>
                </div>
                <div className="compliance-card">
                  <Grid3x3 size={20} />
                  <div>
                    <strong>Immutable Logs</strong>
                    <span>All agent decisions permanently recorded</span>
                  </div>
                </div>
              </div>
            </section>
          )}

          {section === 'settings' && (
            <section className="dashboard-subgrid">
              <article className="dashboard-subpanel">
                <div className="dashboard-subpanel-head">
                  <h2>Workspace Settings</h2>
                  <Settings size={18} />
                </div>
                <div className="dashboard-settings-list">
                  {settingsRows.map((row) => (
                    <div key={row.label} className="dashboard-settings-row">
                      <strong>{row.label}</strong>
                      <span>{row.value}</span>
                    </div>
                  ))}
                </div>
              </article>

              <article className="dashboard-subpanel">
                <div className="dashboard-subpanel-head">
                  <h2>Access</h2>
                  <LogOut size={18} />
                </div>
                <p className="dashboard-subcopy">
                  This area can later hold team management, API keys, and billing controls.
                </p>
              </article>
            </section>
          )}
        </main>

        <aside className="dashboard-feed-panel" aria-label="Activity feed">
          <div className="dashboard-feed-head">
            <h2>{section === 'overview' ? 'Activity Feed' : `${sectionLabel[section]} Feed`}</h2>
            <p>{section === 'overview' ? 'Live recovery events' : 'Section shortcuts and live updates'}</p>
          </div>

          <div className="dashboard-feed-list">
            {feedItems.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>
                No activity for this period.
              </div>
            ) : feedItems.map((item, index) => (
              <motion.div
                key={`${item.paymentId}-${index}`}
                className="dashboard-feed-card"
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: index * 0.05 }}
              >
                <div className="dashboard-feed-icon" aria-hidden="true">
                  {activeFeedIcon(item.icon)}
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
