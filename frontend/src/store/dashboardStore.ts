import { create } from 'zustand';
import type {
  DashboardActivityItem,
  DashboardJourney,
  DashboardJourneyNode,
  Payment,
} from '../types/dashboard';
import { dashboardAPI } from '../services/api';
import type { LiveAgentStatus, LiveDashboardMetrics, LivePayment } from '../services/api';

type DashboardOverviewApi = {
  selected_payment_id: string | null;
  recovery_rate: number;
  target_rate: number;
  total_recovered: number;
  total_payments_processed: number;
  active_recoveries: Array<{
    id: string;
    amount: number;
    status: Payment['status'];
    strategy_used: string;
    recovered_amount: number;
    last_updated: string;
    chargeback_risk?: {
      risk_score_pct: number;
      risk_band: string;
      customer_history: string[];
      product_category: string;
      payment_method: string;
      recovery_path: string;
      evidence_to_store: string[];
      recommended_actions: string[];
      manual_review_required: boolean;
      rationale: string[];
      generated_at: string;
    } | null;
  }>;
  activity_feed: Array<{
    label: string;
    action: string;
    amount: string;
    time: string;
    icon: string;
    payment_id: string;
  }>;
  generated_at: string;
};

type DashboardJourneyApi = {
  payment_id: string;
  transaction_id: string;
  title: string;
  subtitle: string;
  amount: number;
  status: string;
  recovered_amount: number;
  nodes: Array<{
    id: string;
    title: string;
    subtitle: string;
    x: number;
    y: DashboardJourneyNode['y'];
    circle_tone: DashboardJourneyNode['circleTone'];
    completed: boolean;
    current?: boolean;
    time?: string;
    badge?: string;
    badge_tone?: DashboardJourneyNode['badgeTone'];
    detail?: string;
    preview?: string;
    amount?: string;
    reasoning?: string;
    status?: string;
    reason?: string;
  }>;
  chargeback_risk?: {
    risk_score_pct: number;
    risk_band: string;
    customer_history: string[];
    product_category: string;
    payment_method: string;
    recovery_path: string;
    evidence_to_store: string[];
    recommended_actions: string[];
    manual_review_required: boolean;
    rationale: string[];
    generated_at: string;
  } | null;
  generated_at: string;
};

interface DashboardStore {
  payments: Payment[];
  recoveryRate: number;
  totalRecovered: number;
  targetRate: number;
  totalPaymentsProcessed: number;
  selectedPaymentId: string | null;
  activityFeed: DashboardActivityItem[];
  journey: DashboardJourney | null;
  isLoading: boolean;
  error: string | null;
  periodDays: number;
  liveAgents: LiveAgentStatus['agents'];
  liveFallback: {
    recoveryRate: boolean;
    totalRecovered: boolean;
    totalPaymentsProcessed: boolean;
    payments: boolean;
  };

  fetchPayments: () => Promise<void>;
  fetchJourney: (paymentId: string) => Promise<void>;
  loadDashboard: (paymentId?: string) => Promise<void>;
  updatePayment: (id: string, payment: Partial<Payment>) => void;
  setRecoveryMetrics: (rate: number, total: number) => void;
  selectPayment: (paymentId: string) => Promise<void>;
  setPeriod: (days: number) => void;
  refreshLiveData: () => Promise<void>;
}

const mapPayment = (payment: DashboardOverviewApi['active_recoveries'][number]): Payment => ({
  id: payment.id,
  amount: payment.amount,
  status: payment.status,
  strategyUsed: payment.strategy_used,
  recoveredAmount: payment.recovered_amount,
  lastUpdated: payment.last_updated,
  chargebackRisk: payment.chargeback_risk
    ? {
        riskScorePct: payment.chargeback_risk.risk_score_pct,
        riskBand: payment.chargeback_risk.risk_band,
        customerHistory: payment.chargeback_risk.customer_history,
        productCategory: payment.chargeback_risk.product_category,
        paymentMethod: payment.chargeback_risk.payment_method,
        recoveryPath: payment.chargeback_risk.recovery_path,
        evidenceToStore: payment.chargeback_risk.evidence_to_store,
        recommendedActions: payment.chargeback_risk.recommended_actions,
        manualReviewRequired: payment.chargeback_risk.manual_review_required,
        rationale: payment.chargeback_risk.rationale,
        generatedAt: payment.chargeback_risk.generated_at,
      }
    : null,
});

const mapJourneyNode = (node: DashboardJourneyApi['nodes'][number]): DashboardJourneyNode => ({
  id: node.id,
  title: node.title,
  subtitle: node.subtitle,
  x: node.x,
  y: node.y,
  circleTone: node.circle_tone,
  completed: node.completed,
  current: node.current,
  time: node.time,
  badge: node.badge,
  badgeTone: node.badge_tone,
  detail: node.detail,
  preview: node.preview,
  amount: node.amount,
  reasoning: node.reasoning,
  status: node.status,
  reason: node.reason,
});

const mapJourney = (journey: DashboardJourneyApi): DashboardJourney => ({
  paymentId: journey.payment_id,
  transactionId: journey.transaction_id,
  title: journey.title,
  subtitle: journey.subtitle,
  amount: journey.amount,
  status: journey.status,
  recoveredAmount: journey.recovered_amount,
  nodes: journey.nodes.map(mapJourneyNode),
  chargebackRisk: journey.chargeback_risk
    ? {
        riskScorePct: journey.chargeback_risk.risk_score_pct,
        riskBand: journey.chargeback_risk.risk_band,
        customerHistory: journey.chargeback_risk.customer_history,
        productCategory: journey.chargeback_risk.product_category,
        paymentMethod: journey.chargeback_risk.payment_method,
        recoveryPath: journey.chargeback_risk.recovery_path,
        evidenceToStore: journey.chargeback_risk.evidence_to_store,
        recommendedActions: journey.chargeback_risk.recommended_actions,
        manualReviewRequired: journey.chargeback_risk.manual_review_required,
        rationale: journey.chargeback_risk.rationale,
        generatedAt: journey.chargeback_risk.generated_at,
      }
    : null,
  generatedAt: journey.generated_at,
});

const mapActivity = (activity: DashboardOverviewApi['activity_feed'][number]): DashboardActivityItem => ({
  label: activity.label,
  action: activity.action,
  amount: activity.amount,
  time: activity.time,
  icon: activity.icon,
  paymentId: activity.payment_id,
});

const mapLivePayment = (payment: LivePayment): Payment => ({
  id: payment.id,
  amount: payment.amount,
  status: payment.status,
  strategyUsed: payment.strategy_used,
  recoveredAmount: payment.money_recovered,
  lastUpdated: payment.created_at,
  chargebackRisk: null,
});

export const useDashboardStore = create<DashboardStore>((set, get) => ({
  payments: [],
  recoveryRate: 0,
  totalRecovered: 0,
  targetRate: 60,
  totalPaymentsProcessed: 0,
  selectedPaymentId: null,
  activityFeed: [],
  journey: null,
  isLoading: false,
  error: null,
  periodDays: 7,
  liveAgents: [],
  liveFallback: {
    recoveryRate: false,
    totalRecovered: false,
    totalPaymentsProcessed: false,
    payments: false,
  },

  fetchPayments: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await dashboardAPI.getOverview(get().selectedPaymentId ?? undefined, 50, get().periodDays);
      const overview = response.data as DashboardOverviewApi;
      set({
        payments: overview.active_recoveries.map(mapPayment),
        recoveryRate: overview.recovery_rate,
        targetRate: overview.target_rate,
        totalRecovered: overview.total_recovered,
        totalPaymentsProcessed: overview.total_payments_processed,
        selectedPaymentId: overview.selected_payment_id,
        activityFeed: overview.activity_feed.map(mapActivity),
        liveFallback: {
          recoveryRate: overview.recovery_rate === 0,
          totalRecovered: overview.total_recovered === 0,
          totalPaymentsProcessed: overview.total_payments_processed === 0,
          payments: overview.active_recoveries.length === 0,
        },
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Unable to load dashboard overview.',
      });
    } finally {
      set({ isLoading: false });
    }
  },

  fetchJourney: async (paymentId: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await dashboardAPI.getJourney(paymentId);
      set({
        journey: mapJourney(response.data as DashboardJourneyApi),
        selectedPaymentId: paymentId,
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Unable to load recovery journey.',
      });
    } finally {
      set({ isLoading: false });
    }
  },

  loadDashboard: async (paymentId?: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await dashboardAPI.getOverview(paymentId, 50, get().periodDays);
      const overview = response.data as DashboardOverviewApi;
      const nextSelectedPaymentId = paymentId ?? overview.selected_payment_id ?? overview.active_recoveries[0]?.id ?? null;

      set({
        payments: overview.active_recoveries.map(mapPayment),
        recoveryRate: overview.recovery_rate,
        targetRate: overview.target_rate,
        totalRecovered: overview.total_recovered,
        totalPaymentsProcessed: overview.total_payments_processed,
        selectedPaymentId: nextSelectedPaymentId,
        activityFeed: overview.activity_feed.map(mapActivity),
        liveFallback: {
          recoveryRate: overview.recovery_rate === 0,
          totalRecovered: overview.total_recovered === 0,
          totalPaymentsProcessed: overview.total_payments_processed === 0,
          payments: overview.active_recoveries.length === 0,
        },
      });

      if (nextSelectedPaymentId) {
        const journeyResponse = await dashboardAPI.getJourney(nextSelectedPaymentId);
        set({ journey: mapJourney(journeyResponse.data as DashboardJourneyApi) });
      } else {
        set({ journey: null });
      }
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Unable to load dashboard data.',
        journey: null,
      });
    } finally {
      set({ isLoading: false });
    }
  },

  updatePayment: (id, payment) =>
    set((state) => ({
      payments: state.payments.map((currentPayment) =>
        currentPayment.id === id ? { ...currentPayment, ...payment } : currentPayment,
      ),
    })),

  setRecoveryMetrics: (rate, total) =>
    set({
      recoveryRate: rate,
      totalRecovered: total,
    }),

  selectPayment: async (paymentId: string) => {
    await get().fetchJourney(paymentId);
  },

  setPeriod: (days: number) => {
    set({ periodDays: days });
  },

  refreshLiveData: async () => {
    const [metricsResult, agentsResult, paymentsResult] = await Promise.allSettled([
      dashboardAPI.getLiveMetrics(),
      dashboardAPI.getLiveAgentStatus(),
      dashboardAPI.getLivePayments(),
    ]);
    const current = get();
    const metrics = metricsResult.status === 'fulfilled' ? metricsResult.value : null;
    const agents = agentsResult.status === 'fulfilled' ? agentsResult.value : null;
    const livePayments = paymentsResult.status === 'fulfilled' ? paymentsResult.value : null;
    const fallback = current.liveFallback;

    const nextFallback = {
      recoveryRate: fallback.recoveryRate && Boolean(metrics),
      totalRecovered: fallback.totalRecovered && Boolean(metrics),
      totalPaymentsProcessed: fallback.totalPaymentsProcessed && Boolean(metrics),
      payments: fallback.payments && Boolean(livePayments),
    };

    set({
      recoveryRate: fallback.recoveryRate && metrics ? metrics.recovery_rate : current.recoveryRate,
      totalRecovered: fallback.totalRecovered && metrics ? metrics.total_recovered : current.totalRecovered,
      totalPaymentsProcessed: fallback.totalPaymentsProcessed && metrics ? metrics.total_payments : current.totalPaymentsProcessed,
      payments: fallback.payments && livePayments
        ? livePayments.payments.map(mapLivePayment)
        : current.payments,
      liveAgents: agents?.agents ?? current.liveAgents,
      liveFallback: nextFallback,
    });
  },
}));
