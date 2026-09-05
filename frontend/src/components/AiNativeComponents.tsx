import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Lightbulb,
  LoaderCircle,
  MessageSquareText,
  Send,
  ShieldAlert,
  Sparkles,
  Target,
  WandSparkles,
} from 'lucide-react';
import { aiAPI, type ComplianceResult, type IntentPrediction, type StrategySuggestion } from '../services/api';
import './AiNativeComponents.css';

type AsyncState<T> = { value: T | null; loading: boolean; error: string | null };

const initialState = <T,>(): AsyncState<T> => ({ value: null, loading: true, error: null });

const useAiRequest = <T,>(request: () => Promise<T>, dependencies: unknown[]): AsyncState<T> => {
  const [state, setState] = useState<AsyncState<T>>(initialState);

  useEffect(() => {
    let active = true;
    setState(initialState());
    request().then((value) => {
      if (active) setState({ value, loading: false, error: null });
    }).catch((cause: unknown) => {
      if (active) setState({ value: null, loading: false, error: cause instanceof Error ? cause.message : 'AI service unavailable' });
    });
    return () => { active = false; };
    // The caller controls refresh identity with explicit dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);

  return state;
};

const LoadingState = ({ label }: { label: string }) => (
  <div className="ai-inline-state"><LoaderCircle size={17} className="ai-spin" />{label}</div>
);

const ErrorState = ({ message }: { message: string }) => (
  <div className="ai-error-state"><AlertTriangle size={16} />{message}</div>
);

export const MerchantAdvisor = ({ merchantId, metrics = {} }: { merchantId: string; metrics?: Record<string, unknown> }) => {
  const metricsKey = JSON.stringify(metrics);
  const { value, loading, error } = useAiRequest(() => aiAPI.merchantAdvisor(merchantId, metrics), [merchantId, metricsKey]);
  const [detailsOpen, setDetailsOpen] = useState(false);

  return (
    <article className="ai-card ai-advisor-card">
      <div className="ai-card-heading">
        <div className="ai-icon ai-icon-coral"><Bot size={20} /></div>
        <div><p className="ai-kicker">Decision intelligence</p><h3>AI Merchant Advisor</h3></div>
        <span className="ai-live-pill"><span />Live insight</span>
      </div>
      <div className="ai-advisor-body">
        {loading && <LoadingState label="Analyzing merchant patterns..." />}
        {error && <ErrorState message={error} />}
        {!loading && !error && <p className="ai-advice">{value?.advice}</p>}
      </div>
      <div className="ai-card-actions">
        <button type="button" className="ai-button ai-button-primary" onClick={() => setDetailsOpen((open) => !open)}>
          <Sparkles size={15} />{detailsOpen ? 'Hide analysis' : 'Get detailed analysis'}
        </button>
        <a className="ai-button ai-button-quiet" href="#/dashboard/analytics"><Target size={15} />View metrics<ArrowRight size={14} /></a>
      </div>
      {detailsOpen && <div className="ai-detail-drawer"><Lightbulb size={16} /><span>Use this advice alongside the deterministic StrategySelector. Any action still requires supervisor approval.</span></div>}
    </article>
  );
};

export const StrategyOptimizer = ({ paymentId, currentStrategy }: { paymentId: string; currentStrategy?: string }) => {
  const { value, loading, error } = useAiRequest(() => aiAPI.optimizeStrategy(paymentId), [paymentId]);
  const [applied, setApplied] = useState(false);
  if (loading) return <section className="ai-card ai-compact-card"><LoadingState label="Finding a stronger recovery path..." /></section>;
  if (error) return <section className="ai-card ai-compact-card"><ErrorState message={error} /></section>;
  if (!value) return null;
  return (
    <section className="ai-card ai-optimizer-card">
      <div className="ai-card-heading"><div className="ai-icon ai-icon-gold"><WandSparkles size={19} /></div><div><p className="ai-kicker">Advisory experiment</p><h3>AI strategy suggestion</h3></div><span className="ai-confidence">{Math.round(value.confidence * 100)}% confidence</span></div>
      <p className="ai-advice">{value.rationale}</p>
      <div className="ai-comparison-grid"><div><span>Current strategy</span><strong>{currentStrategy ?? value.current_strategy ?? 'Current plan'}</strong></div><ArrowRight size={17} /><div><span>Suggested strategy</span><strong className="ai-positive">{value.suggested_strategy}</strong></div></div>
      <div className="ai-impact"><span>Expected improvement</span><strong>{value.improvement_vs_current}</strong><small>{value.timing} timing window</small></div>
      <button type="button" className={`ai-button ${applied ? 'ai-button-success' : 'ai-button-primary'}`} onClick={() => setApplied(true)} disabled={applied}>{applied ? <><Check size={15} />Queued for supervisor review</> : <>Apply suggestion <ArrowRight size={15} /></>}</button>
    </section>
  );
};

export const ComplianceCheck = ({ paymentId, strategy, action }: { paymentId: string; strategy: string; action: string }) => {
  const { value, loading, error } = useAiRequest(() => aiAPI.checkCompliance(paymentId, strategy, action), [paymentId, strategy, action]);
  if (loading) return <div className="ai-inline-state ai-compliance-loading"><LoaderCircle size={16} className="ai-spin" />Checking compliance before action...</div>;
  if (error) return <div className="ai-compliance-banner is-blocked"><ErrorState message={error} /></div>;
  if (!value) return null;
  const approved = value.compliance_approved;
  return <div className={`ai-compliance-banner ${approved ? 'is-approved' : 'is-blocked'}`}><div className="ai-compliance-mark">{approved ? <CheckCircle2 size={20} /> : <ShieldAlert size={20} />}</div><div className="ai-compliance-copy"><strong>{approved ? 'Compliance approved' : 'Compliance review required'}</strong><span>{approved ? 'Safe to proceed within the checked conditions.' : value.regulation}</span>{!approved && <><ul>{value.precautions.slice(0, 3).map((precaution) => <li key={precaution}>{precaution}</li>)}</ul><em>{value.recommended_action}</em></>}</div></div>;
};

export const CustomerIntentPrediction = ({ paymentId }: { paymentId: string }) => {
  const { value, loading, error } = useAiRequest(() => aiAPI.predictIntent(paymentId), [paymentId]);
  if (loading) return <section className="ai-card ai-compact-card"><LoadingState label="Estimating self-recovery intent..." /></section>;
  if (error) return <section className="ai-card ai-compact-card"><ErrorState message={error} /></section>;
  if (!value) return null;
  const prediction: IntentPrediction = value.prediction;
  const willRecover = prediction.will_self_recover;
  const probability = Math.round(prediction.recovery_probability * 100);
  return <section className={`ai-card ai-intent-card ${willRecover ? 'is-positive' : 'is-caution'}`}><div><p className="ai-kicker">Customer signal</p><h3>Self-recovery intent</h3><strong className="ai-intent-score">{probability}% <span>likely to retry</span></strong><p className="ai-muted">{prediction.reasoning}</p></div><div className="ai-intent-recommendation"><span>Recommendation</span><strong>{value.recommendation === 'skip_contact' ? 'Skip contact' : 'Contact customer'}</strong>{value.recommendation === 'skip_contact' && <small>Save approximately Rs 5 SMS cost</small>}</div></section>;
};

export const PersonalizedMessagePreview = ({ paymentId, strategy }: { paymentId: string; strategy: string }) => {
  const { value, loading, error } = useAiRequest(() => aiAPI.personalizeMessage(paymentId, strategy), [paymentId, strategy]);
  const [sent, setSent] = useState(false);
  if (loading) return <section className="ai-card ai-compact-card"><LoadingState label="Personalizing recovery message..." /></section>;
  if (error) return <section className="ai-card ai-compact-card"><ErrorState message={error} /></section>;
  if (!value) return null;
  return <section className="ai-card ai-message-card"><div className="ai-message-heading"><div><p className="ai-kicker">Supervisor preview</p><h3><MessageSquareText size={17} /> Personalized SMS</h3></div><span className="ai-character-count">{value.character_count} / 160</span></div><p className="ai-message-text">“{value.personalized_message}”</p><div className="ai-message-footer"><span><FileCheck2 size={14} />Ready for review</span><button type="button" className={`ai-button ${sent ? 'ai-button-success' : 'ai-button-primary'}`} onClick={() => setSent(true)} disabled={sent}>{sent ? <><Check size={15} />Sent to supervisor</> : <><Send size={15} />Send for approval</>}</button></div><ComplianceCheck paymentId={paymentId} strategy={strategy} action="send_sms" /></section>;
};

export const AnomalyExplainer = ({ anomaly, context }: { anomaly: string; context: Record<string, unknown> }) => {
  const contextKey = JSON.stringify(context);
  const { value, loading, error } = useAiRequest(() => aiAPI.explainAnomaly(anomaly, context), [anomaly, contextKey]);
  return <section className="ai-card ai-anomaly-card"><div className="ai-card-heading"><div className="ai-icon ai-icon-amber"><Lightbulb size={19} /></div><div><p className="ai-kicker">Explainable operations</p><h3>Why this happened</h3></div><span className="ai-anomaly-tag">{anomaly}</span></div>{loading && <LoadingState label="Tracing the metric change..." />}{error && <ErrorState message={error} />}{!loading && !error && <p className="ai-advice">{value?.explanation}</p>}<div className="ai-card-actions"><button type="button" className="ai-button ai-button-quiet"><Clock3 size={15} />View event timeline</button><button type="button" className="ai-button ai-button-quiet"><ArrowRight size={15} />Review actions</button></div></section>;
};