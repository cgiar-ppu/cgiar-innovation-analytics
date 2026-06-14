// Skills autocomplete
export interface SkillInfo {
  name: string;
  description: string;
  category: 'skill' | 'command';
  invocable?: boolean;
}

// Dashboard
export interface DashboardStats {
  total_sessions: number;
  total_messages: number;
  active_memories: number;
  recent_activity: number;
  active_connections: number;
  total_agents: number;
}

export interface ActivityDataPoint {
  date: string;
  messages: number;
}

// Agents
export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  type: string;  // 'builtin' | 'custom'
  status: 'active' | 'inactive';
  tools: string[];
  model: string;
  color?: string;
  system_prompt?: string;
  tags?: string[];
  is_active?: number;
  created_at?: number | null;
  updated_at?: number | null;
  parent_agent?: string;
  version?: number;
}

// Step configuration for workflow creation
export interface StepConfig {
  agent_id: string;
  sub_agents?: string[];
  extra_instructions?: string;
  max_turns?: number;
}

// Workflows
export interface Workflow {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'running' | 'completed' | 'failed';
  progress: number;
  steps: number;
  agent_sequence: string[];
  initial_prompt: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at: string;
  updated_at: string;
  run_count: number;
  last_run: string | null;
  step_configs?: StepConfig[];
}

export interface WorkflowNode {
  id: string;
  label: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration?: number;
  icon?: string;
  position: { x: number; y: number };
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
}

// Pipeline execution
export interface PipelineEvent {
  type: 'step_start' | 'text' | 'thinking' | 'tool_use' | 'tool_result' | 'step_complete' | 'pipeline_complete' | 'error' | 'cancelled' | 'result' | 'pipeline_cancelled';
  step?: number;
  agent_id?: string;
  agent_name?: string;
  total_steps?: number;
  content?: string;
  tool?: string;
  input?: Record<string, unknown>;
  tool_use_id?: string;
  is_error?: boolean;         // tool_result: indicates the tool returned an error
  results?: Record<string, unknown>;
  message?: string;
  output_preview?: string;    // step_complete: truncated preview of the step output
  duration_s?: number;        // step_complete: wall-clock seconds for the step
  total_duration_s?: number;  // pipeline_complete: total wall-clock seconds for the run
  completed_steps?: number;   // pipeline_cancelled: number of steps that finished before cancellation
  run_log_id?: string;        // pipeline_complete/cancelled: ID of the saved run log
  run_log_path?: string;      // pipeline_complete/cancelled: file path of the saved run log
}

// Workflow Run History
export interface WorkflowRunSummary {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  started_at: number;
  completed_at: number | null;
  total_duration_s: number | null;
  total_cost_usd: number | null;
  initial_prompt: string;
  step_count: number;
  completed_steps: number;
  summary: string | null;
}

export interface WorkflowRunMessage {
  id: number;
  type: string;
  data: Record<string, unknown> | null;
  ts: number;
  tool_use_id: string | null;
  is_error: number;
}

export interface WorkflowRunStep {
  id: number;
  run_id: string;
  step_index: number;
  agent_id: string;
  agent_name: string;
  model: string;
  input_prompt: string;
  output_text: string | null;
  tool_calls_count: number;
  turns: number | null;
  estimated_cost: number | null;
  error: string | null;
  started_at: number;
  completed_at: number | null;
  duration_s: number | null;
  messages: WorkflowRunMessage[];
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  agent_sequence: string[];
  log_filename: string | null;
  progress: number;
  steps: WorkflowRunStep[];
}

// Settings
export interface SettingsConfig {
  theme: 'dark' | 'light';
  model: string;
  fallback_model: string;
  max_turns: number;
  memory_categories: string[];
}

// PRMS Dashboard
export interface PRMSKPIs {
  total_results: number;
  total_innovations: number;
  innovation_uses: number;
  active_initiatives: number;
  countries_covered: number;
  innovation_packages: number;
}

export interface PRMSDashboardData {
  kpis: PRMSKPIs;
  charts: {
    results_by_type: import('../components/chat/chartDetector').ChartData;
    top_countries: import('../components/chat/chartDetector').ChartData;
    irl_distribution: import('../components/chat/chartDetector').ChartData;
    top_initiatives: import('../components/chat/chartDetector').ChartData;
  };
  year?: number | null;
  last_updated: string;
}
