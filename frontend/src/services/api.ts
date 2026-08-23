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

const getApiKey = () => import.meta.env.VITE_API_KEY || localStorage.getItem('verityApiKey') || localStorage.getItem('apiKey') || '';

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
  getOverview: (paymentId?: string, limit = 5) =>
    apiClient.get<unknown>('/dashboard/overview', {
      params: {
        payment_id: paymentId,
        limit,
      },
    }),

  getJourney: (paymentId: string) =>
    apiClient.get<unknown>(`/dashboard/journey/${paymentId}`),
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
  list: () => apiClient.get<{ workflows: Workflow[] }>('/workflows'),
  create: (data: { name: string; target_segment: string; variant?: string; steps: WorkflowStep[] }) =>
    apiClient.post<Workflow>('/workflows/create', data),
};

export const metricsAPI = {
  getSummary: (periodDays = 30) => apiClient.get<Record<string, unknown>>('/metrics/summary', { params: { period_days: periodDays } }),
  getRecoveryRate: () => apiClient.get<{ rate: number; target: number }>('/metrics/recovery-rate'),

  getRecovered: () => apiClient.get<{ amount: number; currency: string }>('/metrics/total-recovered'),
};

export default apiClient;
