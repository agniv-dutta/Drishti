import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowUp, Brain, Check, ChevronDown, ChevronRight, Clock3, GripVertical, Mail, MessageSquare, Phone, Plus, Save, ShieldAlert, Sparkles, StopCircle, Timer, Trash2, TrendingDown, TrendingUp, UserRound, Zap } from 'lucide-react';
import { workflowAPI } from '../services/api';
import type { Workflow, WorkflowAction, WorkflowStep } from '../types/workflow';
import './WorkflowBuilder.css';

const palette: Array<{ type: WorkflowAction; label: string; icon: React.ReactNode; color: string }> = [
  { type: 'retry', label: 'Retry payment', icon: <Zap size={16} />, color: 'coral' },
  { type: 'wait', label: 'Wait', icon: <Timer size={16} />, color: 'gold' },
  { type: 'sms', label: 'Send SMS', icon: <MessageSquare size={16} />, color: 'sage' },
  { type: 'email', label: 'Send email', icon: <Mail size={16} />, color: 'blue' },
  { type: 'call', label: 'Call customer', icon: <Phone size={16} />, color: 'rose' },
  { type: 'offer', label: 'Offer', icon: <Sparkles size={16} />, color: 'violet' },
  { type: 'stop', label: 'Stop recovery', icon: <StopCircle size={16} />, color: 'gray' },
  { type: 'escalate', label: 'Escalate', icon: <UserRound size={16} />, color: 'dark' },
];

type AIRecommendation = {
  id: string;
  name: string;
  successRate: number;
  type: 'ai' | 'custom' | 'historical';
  runs?: number;
  reason?: string;
};

type StepWithConfidence = WorkflowStep & {
  confidence?: number;
  reasoning?: string;
};

const starterSteps: StepWithConfidence[] = [
  { type: 'retry', delay: '0h', confidence: 85, reasoning: 'Immediate retry has 85% success for similar payments' },
  { type: 'sms', delay: '2h', template: 'Payment failed, retry now', confidence: 78, reasoning: 'SMS after 2h works best for this segment' },
  { type: 'email', delay: '24h', template: 'Complete your purchase', confidence: 65, reasoning: 'Email follow-up increases engagement by 23%' },
];

const aiRecommendations: AIRecommendation[] = [
  { id: 'sms-recovery', name: 'SMS Recovery', successRate: 72, type: 'ai', reason: 'Highest success rate this week' },
  { id: 'retry-flow', name: 'Retry', successRate: 45, type: 'ai', reason: 'Quick retry for technical failures' },
  { id: 'call-flow', name: 'Call', successRate: 38, type: 'ai', reason: 'Human intervention for complex cases' },
];

const customTemplates: AIRecommendation[] = [
  { id: 'luxury', name: 'Luxury Customers', successRate: 65, type: 'custom', runs: 2 },
  { id: 'new-customers', name: 'New Customers', successRate: 42, type: 'custom', runs: 15 },
];

const historicalFlows: AIRecommendation[] = [
  { id: 'aggressive', name: 'Too aggressive offers', successRate: 8, type: 'historical', reason: 'Archived - low conversion' },
  { id: 'retry-only', name: 'Retry only', successRate: 22, type: 'historical', reason: 'Consider adding SMS' },
];

const labelFor = (type: WorkflowAction) => palette.find((item) => item.type === type)?.label ?? type;

const WorkflowBuilder: React.FC = () => {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [name, setName] = useState('AI-Optimized Recovery Flow');
  const [segment, setSegment] = useState('high_value');
  const [variant, setVariant] = useState('A');
  const [steps, setSteps] = useState<StepWithConfidence[]>(starterSteps);
  const [selected, setSelected] = useState(0);
  const [dragged, setDragged] = useState<number | null>(null);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [activeTab, setActiveTab] = useState<'ai' | 'custom' | 'historical'>('ai');
  const [abTestEnabled, setAbTestEnabled] = useState(false);
  const [expandedRecommendation, setExpandedRecommendation] = useState<string | null>(null);

  useEffect(() => { void workflowAPI.list().then((response) => setWorkflows(response.data.workflows)).catch(() => undefined); }, []);

  const addStep = (type: WorkflowAction) => {
    const confidence = type === 'sms' ? 78 : type === 'retry' ? 85 : type === 'call' ? 62 : 50;
    const reasoning = type === 'sms' ? 'SMS has 72% historical success' : type === 'retry' ? 'Immediate retry recommended' : 'Based on similar payment patterns';
    setSteps((current) => [...current, { type, delay: type === 'retry' ? '0h' : '1h', confidence, reasoning }]);
    setSelected(steps.length);
  };

  const updateStep = (patch: Partial<StepWithConfidence>) => setSteps((current) => current.map((step, index) => index === selected ? { ...step, ...patch } : step));
  const removeStep = () => { setSteps((current) => current.filter((_, index) => index !== selected)); setSelected(Math.max(0, selected - 1)); };
  const moveStep = (from: number, to: number) => {
    if (from === to) return;
    setSteps((current) => { const next = [...current]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next; });
    setSelected(to);
  };

  const save = async () => {
    setStatus('saving');
    try { const response = await workflowAPI.create({ name, target_segment: segment, variant, steps: steps.map(({ confidence, reasoning, ...step }) => step) }); setWorkflows((current) => [response.data, ...current]); setStatus('saved'); }
    catch { setStatus('error'); }
  };

  const activeStep = steps[selected] ?? steps[0];
  const estimatedSuccess = steps.length > 0 ? Math.round(steps.reduce((acc, step) => acc + (step.confidence || 50), 0) / steps.length) : 0;
  const aiRecommendedSuccess = 72;

  const getRecommendations = () => {
    switch (activeTab) {
      case 'ai': return aiRecommendations;
      case 'custom': return customTemplates;
      case 'historical': return historicalFlows;
      default: return aiRecommendations;
    }
  };

  return <div className="workflow-page">
    <header className="workflow-topbar"><a href="#/dashboard/overview" className="workflow-brand"><span>V</span>Drishti</a><nav><a href="#/dashboard/overview">Operations</a><a className="active" href="#/dashboard/workflows">AI Strategy Lab</a><a href="#/dashboard/analytics">Analytics</a></nav><a href="#/page/client-login" className="workflow-login">Client login</a></header>
    <main className="workflow-main">
      <div className="workflow-breadcrumb"><a href="#/dashboard/overview"><ArrowLeft size={15} />Back to workspace</a><span>/</span><strong>AI Strategy Lab</strong></div>
      <section className="workflow-heading"><div><p className="workflow-kicker">AI-Powered Recovery</p><h1>Build intelligent recovery strategies</h1><p>AI learns what works and guides your workflow design with real-time performance data.</p></div><button type="button" className="workflow-save" onClick={() => void save()} disabled={status === 'saving'}><Save size={16} />{status === 'saving' ? 'Saving...' : 'Save strategy'}</button></section>
      {status === 'saved' && <div className="workflow-toast"><Check size={16} />Strategy saved and ready for deployment.</div>}
      {status === 'error' && <div className="workflow-toast error"><ShieldAlert size={16} />Could not save strategy. Check the API connection.</div>}
      <section className="workflow-meta"><label><span>Strategy name</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>Target segment</span><div className="workflow-input-select"><input value={segment} onChange={(event) => setSegment(event.target.value)} /><ChevronDown size={15} /></div></label><label><span>Experiment variant</span><div className="workflow-input-select"><select value={variant} onChange={(event) => setVariant(event.target.value)}><option>A</option><option>B</option><option>C</option></select><ChevronDown size={15} /></div></label></section>
      <div className="workflow-builder-grid">
        <aside className="workflow-palette">
          <div className="workflow-panel-title"><div><p>AI Intelligence</p><h2>Strategy Library</h2></div></div>
          <div className="strategy-tabs">
            <button type="button" className={activeTab === 'ai' ? 'active' : ''} onClick={() => setActiveTab('ai')}><Brain size={14} />AI Recommends</button>
            <button type="button" className={activeTab === 'custom' ? 'active' : ''} onClick={() => setActiveTab('custom')}><UserRound size={14} />Your Templates</button>
            <button type="button" className={activeTab === 'historical' ? 'active' : ''} onClick={() => setActiveTab('historical')}><Clock3 size={14} />Historical</button>
          </div>
          <div className="strategy-list">
            {getRecommendations().map((rec) => (
              <div key={rec.id} className={`strategy-item ${rec.type}`}>
                <button type="button" className="strategy-header" onClick={() => setExpandedRecommendation(expandedRecommendation === rec.id ? null : rec.id)}>
                  <div className="strategy-info">
                    <strong>{rec.name}</strong>
                    <span className="strategy-success">{rec.successRate}% success</span>
                  </div>
                  <ChevronRight size={14} className={expandedRecommendation === rec.id ? 'expanded' : ''} />
                </button>
                {expandedRecommendation === rec.id && (
                  <div className="strategy-details">
                    {rec.reason && <p>{rec.reason}</p>}
                    {rec.runs && <p>Runs: {rec.runs}</p>}
                    <button type="button" className="strategy-apply" onClick={() => {
                      if (rec.name.includes('SMS')) addStep('sms');
                      else if (rec.name.includes('Retry')) addStep('retry');
                      else if (rec.name.includes('Call')) addStep('call');
                    }}>Apply to canvas</button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="workflow-tip"><Brain size={16} /><p><strong>AI learns from every recovery.</strong> Success rates update weekly based on real payment outcomes.</p></div>
        </aside>

        <section className="workflow-canvas">
          <div className="workflow-panel-title">
            <div><p>Canvas</p><h2>{name}</h2></div>
            <div className="canvas-stats">
              <span className="estimated-success">~{estimatedSuccess}% success</span>
              <span>{steps.length} steps</span>
            </div>
          </div>
          <div className="workflow-track">
            {steps.map((step, index) => (
              <React.Fragment key={`${step.type}-${index}`}>
                <article
                  draggable
                  onDragStart={() => setDragged(index)}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={() => { if (dragged !== null) moveStep(dragged, index); setDragged(null); }}
                  onClick={() => setSelected(index)}
                  className={`workflow-node ${selected === index ? 'selected' : ''}`}
                >
                  <GripVertical className="workflow-grip" size={16} />
                  <span className={`workflow-node-icon ${palette.find((item) => item.type === step.type)?.color}`}>
                    {palette.find((item) => item.type === step.type)?.icon}
                  </span>
                  <div className="workflow-node-content">
                    <strong>{labelFor(step.type)}</strong>
                    <small>{step.delay === '0h' ? 'Immediate' : `After ${step.delay}`}</small>
                    {step.confidence && (
                      <div className="workflow-node-confidence">
                        <Brain size={12} />
                        <span>AI confidence: {step.confidence}%</span>
                      </div>
                    )}
                  </div>
                  <span className="workflow-node-number">{String(index + 1).padStart(2, '0')}</span>
                </article>
                {index < steps.length - 1 && <div className="workflow-connector"><span /></div>}
              </React.Fragment>
            ))}
          </div>
          {steps.length === 0 && <div className="workflow-empty"><Plus size={20} /><p>Add AI-recommended strategies to start your flow.</p></div>}
          
          <div className="workflow-ab-test">
            <label className="ab-test-toggle">
              <input type="checkbox" checked={abTestEnabled} onChange={(e) => setAbTestEnabled(e.target.checked)} />
              <span>A/B Test this flow</span>
            </label>
            {abTestEnabled && (
              <div className="ab-test-details">
                <p>Test on 10% traffic first (5 customers)</p>
                <span className="ab-test-badge">Recommended by AI</span>
              </div>
            )}
          </div>
        </section>

        <aside className="workflow-inspector">
          <div className="workflow-panel-title">
            <div><p>Analytics</p><h2>Performance</h2></div>
          </div>
          
          <div className="performance-comparison">
            <div className="performance-card your-flow">
              <span>Your flow</span>
              <strong>{estimatedSuccess}%</strong>
              <span className="performance-trend">
                {estimatedSuccess >= aiRecommendedSuccess ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                {estimatedSuccess >= aiRecommendedSuccess ? 'Above AI' : 'Below AI'}
              </span>
            </div>
            <div className="performance-card ai-flow">
              <span>AI-recommended</span>
              <strong>{aiRecommendedSuccess}%</strong>
              <span className="performance-trend"><Brain size={14} />Optimal</span>
            </div>
          </div>

          <div className="ai-suggestions">
            <h3><Sparkles size={16} />AI Suggestions</h3>
            <div className="suggestion-item">
              <p>If you add voice call after SMS, success goes {estimatedSuccess}%→{Math.min(estimatedSuccess + 7, 95)}%</p>
              <button type="button" className="suggestion-apply" onClick={() => addStep('call')}>Add Call</button>
            </div>
            <div className="suggestion-item">
              <p>Reduce wait time between steps for faster recovery</p>
              <button type="button" className="suggestion-optimize">Optimize timing</button>
            </div>
          </div>

          {activeStep && (
            <div className="workflow-form">
              <div className="workflow-selected-type">
                <span className={`workflow-node-icon ${palette.find((item) => item.type === activeStep.type)?.color}`}>
                  {palette.find((item) => item.type === activeStep.type)?.icon}
                </span>
                <strong>{labelFor(activeStep.type)}</strong>
              </div>
              {activeStep.reasoning && (
                <div className="step-reasoning">
                  <Brain size={14} />
                  <span>{activeStep.reasoning}</span>
                </div>
              )}
              <label><span>Delay after previous step</span><input value={activeStep.delay} onChange={(event) => updateStep({ delay: event.target.value })} placeholder="2h or 7d" /></label>
              {['sms', 'email'].includes(activeStep.type) && <label><span>Message template</span><textarea value={activeStep.template ?? ''} onChange={(event) => updateStep({ template: event.target.value })} placeholder="Write the customer message..." /></label>}
              {activeStep.type === 'call' && <label><span>Call tone</span><input value={activeStep.tone ?? ''} onChange={(event) => updateStep({ tone: event.target.value })} placeholder="VIP, empathetic" /></label>}
              {activeStep.type === 'offer' && <label><span>Maximum discount</span><input value={activeStep.max_discount ?? ''} onChange={(event) => updateStep({ max_discount: event.target.value })} placeholder="10%" /></label>}
              <button type="button" className="workflow-delete-step" onClick={removeStep}><Trash2 size={16} />Remove step</button>
            </div>
          )}
        </aside>
      </div>
    </main>
  </div>;
};
export default WorkflowBuilder;
