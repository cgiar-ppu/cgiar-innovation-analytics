import type { DashboardStats, ActivityDataPoint, AgentInfo, Workflow } from './types-extended';
import type { Session, Memory } from './types';

export const mockDashboardStats: DashboardStats = {
  total_sessions: 12,
  total_messages: 247,
  active_memories: 18,
  recent_activity: 34,
  active_connections: 1,
  total_agents: 5,
};

export const mockActivityData: ActivityDataPoint[] = Array.from({ length: 7 }, (_, i) => {
  const d = new Date();
  d.setDate(d.getDate() - (6 - i));
  return {
    date: d.toLocaleDateString('en-US', { weekday: 'short' }),
    messages: Math.floor(Math.random() * 40) + 5,
  };
});

export const mockAgents: AgentInfo[] = [
  {
    id: 'orchestrator',
    name: 'Orchestrator (Full Team)',
    description: 'The main orchestrator with access to all subagents — a full agentic team',
    type: 'builtin',
    status: 'active' as const,
    tools: ['All tools + Task delegation'],
    model: 'opus',
    color: '#8b5cf6',
  },
  {
    id: 'data_analysis',
    name: 'Data Analysis',
    description: 'Statistical analysis, EDA, hypothesis testing, regression, data wrangling',
    type: 'builtin',
    status: 'active',
    tools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'WebSearch', 'WebFetch'],
    model: 'sonnet',
    color: '#3b82f6',
  },
  {
    id: 'visualization_reporting',
    name: 'Visualization & Reporting',
    description: 'Charts, dashboards, reports, publication-quality figures',
    type: 'builtin',
    status: 'active',
    tools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'WebSearch', 'WebFetch'],
    model: 'sonnet',
    color: '#8b5cf6',
  },
  {
    id: 'research_methodology',
    name: 'Research Methodology',
    description: 'Study design, sampling, power analysis, experimental design',
    type: 'builtin',
    status: 'active',
    tools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'WebSearch', 'WebFetch'],
    model: 'sonnet',
    color: '#10b981',
  },
  {
    id: 'code_automation',
    name: 'Code & Automation',
    description: 'Data pipelines, ETL, web scraping, API integration, scripting',
    type: 'builtin',
    status: 'active',
    tools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'WebSearch', 'WebFetch'],
    model: 'sonnet',
    color: '#f59e0b',
  },
  {
    id: 'computer_use',
    name: 'Computer Use',
    description: 'GUI interaction — browsing, editing documents, clicking, screenshots',
    type: 'builtin',
    status: 'active',
    tools: ['Bash', 'mcp__synapsis__computer'],
    model: 'sonnet',
    color: '#ef4444',
  },
];

export const mockWorkflows: Workflow[] = [
  {
    id: 'wf-demo-1',
    name: 'Data → Visualization Pipeline',
    description: 'Analyze dataset then generate publication-quality charts',
    status: 'completed',
    progress: 100,
    steps: 2,
    agent_sequence: ['data_analysis', 'visualization_reporting'],
    initial_prompt: 'Analyze sales data and create charts',
    nodes: [
      { id: 'n1', label: 'Data Analysis', status: 'completed', duration: 12000, position: { x: 100, y: 100 } },
      { id: 'n2', label: 'Visualization', status: 'completed', duration: 8000, position: { x: 400, y: 100 } },
    ],
    edges: [{ id: 'e1', source: 'n1', target: 'n2' }],
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date(Date.now() - 3600000).toISOString(),
    run_count: 3,
    last_run: new Date(Date.now() - 3600000).toISOString(),
  },
];

export const mockSessions: Session[] = [
  {
    session_id: 'demo-001',
    title: 'Example Analysis Session',
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date(Date.now() - 3600000).toISOString(),
    model: 'claude-sonnet-4-6',
    message_count: 24,
    pinned: false,
  },
];

export const mockMemories: Memory[] = [
  {
    id: 1,
    category: 'best_practice',
    content: 'Always check data distributions before running parametric tests',
    importance: 8,
    source_session: 'demo-001',
    active: 1,
    tags: 'statistics, data quality',
    created_at: Date.now() / 1000 - 172800,
    updated_at: Date.now() / 1000 - 172800,
    access_count: 5,
  },
];

export const mockFiles = [
  { name: 'analysis_results.csv', size: 24500, modified: Date.now() / 1000 - 7200, is_dir: false },
  { name: 'report.html', size: 18200, modified: Date.now() / 1000 - 3600, is_dir: false },
  { name: 'uploads', size: 0, modified: Date.now() / 1000 - 86400, is_dir: true },
];
