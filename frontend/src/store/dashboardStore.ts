import { create } from 'zustand';
import type { Payment } from '../types/dashboard';

interface DashboardStore {
  payments: Payment[];
  recoveryRate: number;
  totalRecovered: number;

  fetchPayments: () => Promise<void>;
  updatePayment: (id: string, payment: Partial<Payment>) => void;
  setRecoveryMetrics: (rate: number, total: number) => void;
}

export const useDashboardStore = create<DashboardStore>((set) => ({
  payments: [],
  recoveryRate: 0,
  totalRecovered: 0,

  fetchPayments: async () => {
    const response = await fetch('/api/payments');
    const data: Payment[] = await response.json();
    set({ payments: data });
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
}));
