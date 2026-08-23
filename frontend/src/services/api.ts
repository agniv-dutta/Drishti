import axios, { type AxiosInstance } from 'axios';
import type { Payment } from '../types/dashboard';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('authToken');

  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

export const paymentsAPI = {
  list: (filters?: { status?: string; merchant_id?: string }) =>
    apiClient.get<Payment[]>('/payments', { params: filters }),

  get: (id: string) => apiClient.get<Payment>(`/payments/${id}`),

  ingest: (data: unknown) => apiClient.post('/payments/ingest', data),
};

export const recoveryAPI = {
  listActive: () => apiClient.get('/recovery/active'),

  detect: (paymentId: string) =>
    apiClient.post('/recovery/detect', { payment_id: paymentId }),

  execute: (recoveryId: string) => apiClient.post(`/recovery/${recoveryId}/execute`, {}),
};

export const metricsAPI = {
  getRecoveryRate: () => apiClient.get<{ rate: number; target: number }>('/metrics/recovery-rate'),

  getRecovered: () => apiClient.get<{ amount: number; currency: string }>('/metrics/total-recovered'),
};

export default apiClient;
