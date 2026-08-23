import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import type { DashboardJourney, DashboardOverview, Payment } from '../types/dashboard';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

const getApiKey = () => import.meta.env.VITE_API_KEY || localStorage.getItem('verityApiKey') || localStorage.getItem('apiKey') || '';

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const apiKey = getApiKey();
  const authToken = localStorage.getItem('authToken');

  if (apiKey) {
    if (typeof config.headers.set === 'function') {
      config.headers.set('X-API-Key', apiKey);
    } else {
      config.headers['X-API-Key'] = apiKey;
    }
  }

  if (authToken) {
    if (typeof config.headers.set === 'function') {
      config.headers.set('Authorization', `Bearer ${authToken}`);
    } else {
      config.headers.Authorization = `Bearer ${authToken}`;
    }
  }

  return config;
});

export const dashboardAPI = {
  getOverview: (paymentId?: string, limit = 5) =>
    apiClient.get<DashboardOverview>('/dashboard/overview', {
      params: {
        payment_id: paymentId,
        limit,
      },
    }),

  getJourney: (paymentId: string) =>
    apiClient.get<DashboardJourney>(`/dashboard/journey/${paymentId}`),
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

export const metricsAPI = {
  getRecoveryRate: () => apiClient.get<{ rate: number; target: number }>('/metrics/recovery-rate'),

  getRecovered: () => apiClient.get<{ amount: number; currency: string }>('/metrics/total-recovered'),
};

export default apiClient;
