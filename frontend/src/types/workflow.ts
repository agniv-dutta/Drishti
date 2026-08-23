export type WorkflowAction = 'retry' | 'wait' | 'sms' | 'email' | 'call' | 'offer' | 'stop' | 'escalate';

export type WorkflowStep = {
  type: WorkflowAction;
  delay: string;
  template?: string;
  tone?: string;
  max_discount?: string;
};

export type Workflow = {
  id: string;
  name: string;
  target_segment: string;
  variant?: string;
  steps: WorkflowStep[];
  success_rate?: number;
  created_at: string;
};
