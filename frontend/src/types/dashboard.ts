export type PaymentStatus = 'failed' | 'recovered' | 'escalated';

export interface Payment {
  id: string;
  amount: number;
  status: PaymentStatus;
  strategyUsed: string;
  recoveredAmount: number;
}
