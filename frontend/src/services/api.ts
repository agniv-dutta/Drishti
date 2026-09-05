import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import type { DashboardJourney, Payment } from '../types/dashboard';
import type { Workflow, WorkflowStep } from '../types/workflow';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

const getApiKey = () => import.meta.env.VITE_API_KEY || localStorage.getItem('DrishtiApiKey') || localStorage.getItem('apiKey') || '';

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const headers = config.headers ?? {};
  const apiKey = getApiKey();
  const authToken = localStorage.getItem('authToken');

  if (apiKey) {
    if (typeof headers.set === 'function') {
      headers.set('X-API-Key', apiKey);
    } else {
      headers['X-API-Key'] = apiKey;
    }
  }

  if (authToken) {
    if (typeof headers.set === 'function') {
      headers.set('Authorization', `Bearer ${authToken}`);
    } else {
      headers.Authorization = `Bearer ${authToken}`;
    }
  }

  config.headers = headers;
  return config;
});

export const dashboardAPI = {
  getOverview: (paymentId?: string, limit = 5, periodDays = 7) =>
    apiClient.get<unknown>('/dashboard/overview', {
      params: {
        payment_id: paymentId,
        limit,
        period_days: periodDays,
      },
    }).then((response) => ({ ...response, data: (response.data as { data?: unknown }).data ?? response.data })),

  getJourney: (paymentId: string) =>
    apiClient.get<unknown>(`/dashboard/journey/${paymentId}`)
      .then((response) => ({ ...response, data: (response.data as { data?: unknown }).data ?? response.data })),

  getMetricsSummary: (period: 'current' | 'monthly' = 'current') =>
    apiClient.get<{ data: PerformanceMetrics }>('/dashboard/metrics-summary', { params: { period } })
      .then((response) => ({ ...response, data: response.data.data })),
};

export type PerformanceMetrics = {
  period: string;
  total_payments: number;
  total_payments_change: number;
  recovery_rate: number;
  recovery_target: number;
  total_recovered: number;
  weekly_change: number;
  avg_cost_per_recovery: number;
  retry_recovered: number;
  sms_recovered: number;
  call_recovered: number;
  timestamp: string;
};

export const paymentsAPI = {
  list: (_filters?: { status?: string; merchant_id?: string }) =>
    dashboardAPI.getOverview(),

  get: (id: string) => apiClient.get<Payment>(`/payment/${id}`),

  ingest: (data: unknown) => apiClient.post('/payment/ingest', data),
};

export const recoveryAPI = {
  listActive: (paymentId?: string) => dashboardAPI.getOverview(paymentId),

  detect: (paymentId: string) =>
    apiClient.post('/recovery/detect', { payment_id: paymentId }),

  execute: (recoveryId: string) => apiClient.post(`/recovery/${recoveryId}/execute`, {}),
};

export const workflowAPI = {
  list: () => apiClient.get<{ workflows: Workflow[] }>('/workflows')
    .then((response) => unwrap(response)),
  create: (data: { name: string; target_segment: string; variant?: string; steps: WorkflowStep[] }) =>
    apiClient.post<Workflow>('/workflows/create', data)
      .then((response) => unwrap(response)),
};

export const metricsAPI = {
  getSummary: (periodDays = 30) => apiClient.get<Record<string, unknown>>('/metrics/summary', { params: { period_days: periodDays } }),
  getRecoveryRate: () => apiClient.get<{ rate: number; target: number }>('/metrics/recovery-rate'),

  getRecovered: () => apiClient.get<{ amount: number; currency: string }>('/metrics/total-recovered'),
};

export type ReceivablesInvoice = {
  id: string;
  invoice_number: string;
  customer_name: string;
  contact_name: string;
  customer_email: string;
  amount: number;
  due_date: string;
  days_overdue: number;
  payment_terms: string;
  status: string;
  reminder_count: number;
  last_reminder: string | null;
  risk_score: number;
  recommended_action: string;
  reminders: Array<{ id: string; sent_at: string; template: string; status: string }>;
  payment_promises: Array<{ id: string; promised_date: string; promised_amount: number; status: string }>;
};

export type DsoMetrics = {
  dso: number;
  benchmark: number;
  improvement: string;
  overdue_invoices: number;
  total_overdue_amount: number;
  total_accounts_receivable: number;
  total_sales_period: number;
};

const unwrap = <T>(response: { data: { data?: T } | T }): T => {
  const body = response.data;
  return (body && typeof body === 'object' && 'data' in body ? body.data : body) as T;
};

export const receivablesAPI = {
  list: (merchantId: string, sortBy: 'amount' | 'days_overdue' | 'due_date', descending = true) =>
    apiClient.get<{ data: { invoices: ReceivablesInvoice[] } }>('/recovery/b2b/invoices', {
      params: { merchant_id: merchantId, sort_by: sortBy, descending },
    }).then((response) => unwrap(response)),
  dso: (merchantId: string) =>
    apiClient.get<{ data: DsoMetrics }>('/recovery/b2b/dso-tracker', { params: { merchant_id: merchantId } })
      .then((response) => unwrap(response)),
  sendReminder: (invoiceId: string) =>
    apiClient.post('/recovery/b2b/send-reminder', null, { params: { invoice_id: invoiceId } }),
};

export type SubscriptionPayment = {
  id: string;
  customer_id: string;
  customer_name: string;
  customer_email: string;
  subscription_id: string;
  subscription_name: string;
  billing_cycle: number;
  amount: number;
  failure_reason: string;
  retry_count: number;
  retry_schedule: string[];
  status: 'failed' | 'retrying' | 'recovered' | 'suspended';
  churn_risk: number;
  last_action: string | null;
  next_retry_at: string | null;
  events: Array<{ id: string; action: string; status: string; message: string; scheduled_for: string | null }>;
};

export type SubscriptionAction = {
  subscription_payment_id: string;
  strategy: string;
  confidence: number;
  message: string;
  next_retry: string | null;
  days_until_suspension?: number | null;
};

export const subscriptionsAPI = {
  list: (merchantId: string) =>
    apiClient.get<{ data: { payments: SubscriptionPayment[] } }>('/recovery/subscription/payments', { params: { merchant_id: merchantId } })
      .then((response) => unwrap(response)),
  handleFailure: (paymentId: string) =>
    apiClient.post<{ data: SubscriptionAction }>('/recovery/subscription/handle-failure', null, { params: { subscription_payment_id: paymentId } })
      .then((response) => unwrap(response)),
  churnRisk: (customerId: string) =>
    apiClient.get('/recovery/subscription/churn-risk', { params: { customer_id: customerId } })
      .then((response) => unwrap(response)),
};

export type VoiceCall = {
  call_id: string;
  payment_id: string;
  language: string;
  status: string;
  ivr_prompt: { greeting: string; lines: string[]; options: Record<string, string>; language: string };
  customer_choice: string | null;
  resulting_action: string | null;
  action_message: string | null;
  duration_seconds: number;
  recording_available: boolean;
  recording_url: string | null;
  recording_consent: boolean;
  initiated_at: string;
  completed_at: string | null;
};

export type VoiceCallStart = {
  call_id: string;
  status: string;
  language: string;
  estimated_duration: string;
  callback_url: string;
  recording_consent: boolean;
};

export const voiceAPI = {
  initiate: (paymentId: string, recordingConsent = false) =>
    apiClient.post<{ data: VoiceCallStart }>('/recovery/voice/initiate-call', null, {
      params: { payment_id: paymentId, recording_consent: recordingConsent },
    }).then((response) => unwrap(response)),
  get: (callId: string) =>
    apiClient.get<{ data: VoiceCall }>(`/recovery/voice/calls/${callId}`).then((response) => unwrap(response)),
};

export default apiClient;
