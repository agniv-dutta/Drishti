import { create } from 'zustand';
import type {
  DashboardActivityItem,
  DashboardJourney,
  DashboardJourneyNode,
  Payment,
} from '../types/dashboard';
import { dashboardAPI } from '../services/api';

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

  fetchPayments: () => Promise<void>;
  fetchJourney: (paymentId: string) => Promise<void>;
  loadDashboard: (paymentId?: string) => Promise<void>;
  updatePayment: (id: string, payment: Partial<Payment>) => void;
  setRecoveryMetrics: (rate: number, total: number) => void;
  selectPayment: (paymentId: string) => Promise<void>;
}

const mapPayment = (payment: DashboardOverviewApi['active_recoveries'][number]): Payment => ({
  id: payment.id,
  amount: payment.amount,
  status: payment.status,
  strategyUsed: payment.strategy_used,
  recoveredAmount: payment.recovered_amount,
  lastUpdated: payment.last_updated,
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

  fetchPayments: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await dashboardAPI.getOverview(get().selectedPaymentId ?? undefined, 5);
      const overview = response.data as DashboardOverviewApi;
      set({
        payments: overview.active_recoveries.map(mapPayment),
        recoveryRate: overview.recovery_rate,
        targetRate: overview.target_rate,
        totalRecovered: overview.total_recovered,
        totalPaymentsProcessed: overview.total_payments_processed,
        selectedPaymentId: overview.selected_payment_id,
        activityFeed: overview.activity_feed.map(mapActivity),
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
      const response = await dashboardAPI.getOverview(paymentId, 5);
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
}));
