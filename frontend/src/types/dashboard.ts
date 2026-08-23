export type PaymentStatus = 'failed' | 'recovered' | 'escalated';

export interface Payment {
  id: string;
  amount: number;
  status: PaymentStatus;
  strategyUsed: string;
  recoveredAmount: number;
  lastUpdated?: string;
}

export interface DashboardActivityItem {
  label: string;
  action: string;
  amount: string;
  time: string;
  icon: string;
  paymentId: string;
}

export type JourneyTone = 'coral' | 'rose' | 'gold';
export type JourneyBadgeTone = 'gray' | 'sage' | 'coral' | 'rose' | 'gold';
export type JourneyPosition = 'above' | 'below';

export interface DashboardJourneyNode {
  id: string;
  title: string;
  subtitle: string;
  x: number;
  y: JourneyPosition;
  circleTone: JourneyTone;
  completed: boolean;
  current?: boolean;
  time?: string;
  badge?: string;
  badgeTone?: JourneyBadgeTone;
  detail?: string;
  preview?: string;
  amount?: string;
  reasoning?: string;
  status?: string;
  reason?: string;
}

export interface DashboardJourney {
  paymentId: string;
  transactionId: string;
  title: string;
  subtitle: string;
  amount: number;
  status: string;
  recoveredAmount: number;
  nodes: DashboardJourneyNode[];
  generatedAt: string;
}

export interface DashboardOverview {
  selectedPaymentId: string | null;
  recoveryRate: number;
  targetRate: number;
  totalRecovered: number;
  totalPaymentsProcessed: number;
  activeRecoveries: Payment[];
  activityFeed: DashboardActivityItem[];
  generatedAt: string;
}
