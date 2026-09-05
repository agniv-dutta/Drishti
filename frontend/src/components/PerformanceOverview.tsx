import React, { useEffect, useState } from 'react';
import { Activity, ArrowUpRight, Banknote, ChartNoAxesCombined, Coins, LoaderCircle } from 'lucide-react';
import { dashboardAPI, type PerformanceMetrics } from '../services/api';
import './PerformanceOverview.css';

type PerformanceOverviewProps = {
  period?: 'current' | 'monthly';
};

const currency = (value: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value);

const PerformanceOverview: React.FC<PerformanceOverviewProps> = ({ period = 'current' }) => {
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void dashboardAPI.getMetricsSummary(period)
      .then((response) => {
        if (active) setMetrics(response.data);
      })
      .catch(() => {
        if (active) setError('Performance metrics are temporarily unavailable.');
      });
    return () => { active = false; };
  }, [period]);

  const recoveryProgress = metrics ? Math.min((metrics.recovery_rate / Math.max(metrics.recovery_target, 1)) * 100, 100) : 0;

  return (
    <section className="performance-overview" aria-labelledby="performance-overview-title">
      <div className="performance-overview-header">
        <div>
          <p className="performance-eyebrow">Live performance</p>
          <h2 id="performance-overview-title">Performance Overview</h2>
        </div>
        <span className="performance-period">{period === 'monthly' ? 'Last 30 days' : 'Last 7 days'}</span>
      </div>

      {error && <p className="performance-error">{error}</p>}
      <div className="performance-grid" aria-busy={!metrics}>
        <article className="performance-card performance-card-coral">
          <div className="performance-card-top"><span>Total Payments</span><Banknote size={19} /></div>
          <strong>{metrics ? metrics.total_payments.toLocaleString('en-IN') : <LoaderCircle className="performance-spinner" size={22} />}</strong>
          <p><ArrowUpRight size={14} /> {metrics?.total_payments_change ?? 0}% this period</p>
        </article>

        <article className="performance-card performance-card-gold">
          <div className="performance-card-top"><span>Recovery Rate</span><ChartNoAxesCombined size={19} /></div>
          <strong>{metrics ? `${metrics.recovery_rate.toFixed(1)}%` : <LoaderCircle className="performance-spinner" size={22} />}</strong>
          <div className="performance-progress"><span style={{ width: `${recoveryProgress}%` }} /></div>
          <p>Target: {metrics?.recovery_target ?? 60}%</p>
        </article>

        <article className="performance-card performance-card-rose">
          <div className="performance-card-top"><span>Money Recovered</span><Coins size={19} /></div>
          <strong>{metrics ? currency(metrics.total_recovered) : <LoaderCircle className="performance-spinner" size={22} />}</strong>
          <p><ArrowUpRight size={14} /> {metrics?.weekly_change ?? 0}% vs prior period</p>
          {metrics && <div className="performance-breakdown"><span>Retry {currency(metrics.retry_recovered)}</span><span>SMS {currency(metrics.sms_recovered)}</span><span>Call {currency(metrics.call_recovered)}</span></div>}
        </article>

        <article className="performance-card performance-card-sage">
          <div className="performance-card-top"><span>Avg Cost / Recovery</span><Activity size={19} /></div>
          <strong>{metrics ? currency(metrics.avg_cost_per_recovery) : <LoaderCircle className="performance-spinner" size={22} />}</strong>
          <p>Calculated from completed recoveries</p>
        </article>
      </div>
    </section>
  );
};

export default PerformanceOverview;