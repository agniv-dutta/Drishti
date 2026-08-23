import React, { useEffect, useState } from 'react';
import { ArrowLeft, Check, ChevronDown, Clock3, GripVertical, Mail, MessageSquare, Phone, Plus, Save, ShieldAlert, Sparkles, StopCircle, Timer, Trash2, UserRound, Zap } from 'lucide-react';
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
const starterSteps: WorkflowStep[] = [
  { type: 'retry', delay: '0h' },
  { type: 'sms', delay: '2h', template: 'Payment failed, retry now' },
  { type: 'email', delay: '24h', template: 'Complete your purchase' },
  { type: 'offer', delay: '48h', max_discount: '10%' },
  { type: 'escalate', delay: '7d' },
];
const labelFor = (type: WorkflowAction) => palette.find((item) => item.type === type)?.label ?? type;

const WorkflowBuilder: React.FC = () => {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [name, setName] = useState('Luxury Customers Recovery');
  const [segment, setSegment] = useState('high_value');
  const [variant, setVariant] = useState('A');
  const [steps, setSteps] = useState<WorkflowStep[]>(starterSteps);
  const [selected, setSelected] = useState(0);
  const [dragged, setDragged] = useState<number | null>(null);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => { void workflowAPI.list().then((response) => setWorkflows(response.data.workflows)).catch(() => undefined); }, []);

  const addStep = (type: WorkflowAction) => {
    setSteps((current) => [...current, { type, delay: type === 'retry' ? '0h' : '1h' }]);
    setSelected(steps.length);
  };
  const updateStep = (patch: Partial<WorkflowStep>) => setSteps((current) => current.map((step, index) => index === selected ? { ...step, ...patch } : step));
  const removeStep = () => { setSteps((current) => current.filter((_, index) => index !== selected)); setSelected(Math.max(0, selected - 1)); };
  const moveStep = (from: number, to: number) => {
    if (from === to) return;
    setSteps((current) => { const next = [...current]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next; });
    setSelected(to);
  };
  const save = async () => {
    setStatus('saving');
    try { const response = await workflowAPI.create({ name, target_segment: segment, variant, steps }); setWorkflows((current) => [response.data, ...current]); setStatus('saved'); }
    catch { setStatus('error'); }
  };
  const activeStep = steps[selected] ?? steps[0];

  return <div className="workflow-page">
    <header className="workflow-topbar"><a href="#/dashboard/overview" className="workflow-brand"><span>V</span>Verity</a><nav><a href="#/dashboard/overview">Operations</a><a className="active" href="#/dashboard/workflows">Workflow studio</a><a href="#/dashboard/analytics">Analytics</a></nav><a href="#/page/client-login" className="workflow-login">Client login</a></header>
    <main className="workflow-main">
      <div className="workflow-breadcrumb"><a href="#/dashboard/overview"><ArrowLeft size={15} />Back to workspace</a><span>/</span><strong>Workflow studio</strong></div>
      <section className="workflow-heading"><div><p className="workflow-kicker">Visual automation</p><h1>Build a recovery workflow</h1><p>Compose a customer journey, then let Drishti execute every step and record the outcome.</p></div><button type="button" className="workflow-save" onClick={() => void save()} disabled={status === 'saving'}><Save size={16} />{status === 'saving' ? 'Saving...' : 'Save workflow'}</button></section>
      {status === 'saved' && <div className="workflow-toast"><Check size={16} />Workflow saved and ready for assignment.</div>}
      {status === 'error' && <div className="workflow-toast error"><ShieldAlert size={16} />Could not save workflow. Check the API connection.</div>}
      <section className="workflow-meta"><label><span>Workflow name</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>Target segment</span><div className="workflow-input-select"><input value={segment} onChange={(event) => setSegment(event.target.value)} /><ChevronDown size={15} /></div></label><label><span>Experiment variant</span><div className="workflow-input-select"><select value={variant} onChange={(event) => setVariant(event.target.value)}><option>A</option><option>B</option><option>C</option></select><ChevronDown size={15} /></div></label></section>
      <div className="workflow-builder-grid">
        <aside className="workflow-palette"><div className="workflow-panel-title"><div><p>Library</p><h2>Actions</h2></div><span>Drag or add</span></div><div className="workflow-action-list">{palette.map((item) => <button type="button" key={item.type} onClick={() => addStep(item.type)}><span className={`workflow-action-icon ${item.color}`}>{item.icon}</span><span>{item.label}</span><Plus size={15} /></button>)}</div><div className="workflow-tip"><Clock3 size={16} /><p><strong>Every action is logged.</strong> Keep waits relative to the payment failure so the flow stays portable across segments.</p></div></aside>
        <section className="workflow-canvas"><div className="workflow-panel-title"><div><p>Canvas</p><h2>{name}</h2></div><span>{steps.length} steps</span></div><div className="workflow-track">{steps.map((step, index) => <React.Fragment key={`${step.type}-${index}`}><article draggable onDragStart={() => setDragged(index)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (dragged !== null) moveStep(dragged, index); setDragged(null); }} onClick={() => setSelected(index)} className={`workflow-node ${selected === index ? 'selected' : ''}`}><GripVertical className="workflow-grip" size={16} /><span className={`workflow-node-icon ${palette.find((item) => item.type === step.type)?.color}`}>{palette.find((item) => item.type === step.type)?.icon}</span><div><strong>{labelFor(step.type)}</strong><small>{step.delay === '0h' ? 'Immediate' : `After ${step.delay}`}</small></div><span className="workflow-node-number">{String(index + 1).padStart(2, '0')}</span></article>{index < steps.length - 1 && <div className="workflow-connector"><span /></div>}</React.Fragment>)}</div>{steps.length === 0 && <div className="workflow-empty"><Plus size={20} /><p>Add an action from the library to start your flow.</p></div>}</section>
        <aside className="workflow-inspector"><div className="workflow-panel-title"><div><p>Configure</p><h2>Step {String(selected + 1).padStart(2, '0')}</h2></div><button type="button" aria-label="Delete selected step" onClick={removeStep}><Trash2 size={16} /></button></div>{activeStep ? <div className="workflow-form"><div className="workflow-selected-type"><span className={`workflow-node-icon ${palette.find((item) => item.type === activeStep.type)?.color}`}>{palette.find((item) => item.type === activeStep.type)?.icon}</span><strong>{labelFor(activeStep.type)}</strong></div><label><span>Delay after previous step</span><input value={activeStep.delay} onChange={(event) => updateStep({ delay: event.target.value })} placeholder="2h or 7d" /></label>{['sms', 'email'].includes(activeStep.type) && <label><span>Message template</span><textarea value={activeStep.template ?? ''} onChange={(event) => updateStep({ template: event.target.value })} placeholder="Write the customer message..." /></label>}{activeStep.type === 'call' && <label><span>Call tone</span><input value={activeStep.tone ?? ''} onChange={(event) => updateStep({ tone: event.target.value })} placeholder="VIP, empathetic" /></label>}{activeStep.type === 'offer' && <label><span>Maximum discount</span><input value={activeStep.max_discount ?? ''} onChange={(event) => updateStep({ max_discount: event.target.value })} placeholder="10%" /></label>}<div className="workflow-form-note"><ShieldAlert size={15} /><span>Discounts remain subject to margin and compliance guardrails.</span></div></div> : <p className="workflow-inspector-empty">Select a step to configure it.</p>}</aside>
      </div>
      <section className="workflow-saved"><div className="workflow-panel-title"><div><p>Your library</p><h2>Saved workflows</h2></div><span>{workflows.length} saved</span></div>{workflows.length === 0 ? <p className="workflow-no-saved">Your saved workflows will appear here.</p> : <div className="workflow-saved-list">{workflows.slice(0, 3).map((workflow) => <div key={workflow.id}><span>{workflow.name}</span><small>{workflow.target_segment} · variant {workflow.variant ?? 'A'}</small><strong>{workflow.success_rate ? `${Math.round(workflow.success_rate * 100)}% success` : 'New'}</strong></div>)}</div>}</section>
    </main>
  </div>;
};
export default WorkflowBuilder;
