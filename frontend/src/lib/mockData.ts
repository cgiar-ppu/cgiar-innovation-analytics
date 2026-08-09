import type { DashboardStats, ActivityDataPoint, AgentInfo, Workflow, PRMSDashboardData } from './types-extended';
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

export const mockPRMSDashboard: PRMSDashboardData = {
  kpis: {
    total_results: 2755,
    total_innovations: 2006,
    innovation_uses: 669,
    active_initiatives: 54,
    countries_covered: 124,
    innovation_packages: 95,
  },
  charts: {
    results_by_type: {
      chartType: 'pie',
      title: 'Innovations by Type',
      description: 'Distribution of innovation results across types',
      data: [
        { type: 'Innovation development', count: 2006 },
        { type: 'Innovations in use', count: 669 },
        { type: 'Innovation Package', count: 95 },
      ],
      series: [{ key: 'count', label: 'Innovations' }],
      xAxisKey: 'type',
    },
    // F13: one bar per country, stacked by innovation readiness level. Mirrors
    // the backend response shape (irl_<level_id> fields + an ordered series
    // list, low readiness first, "Not reported" last).
    top_countries: {
      chartType: 'stackedBar',
      title: 'Top 10 Countries by Innovation Readiness (2025)',
      description:
        "Countries with the most Innovation Developments, each bar split by innovation readiness level (IRL, low to high). A result code is counted once per country at its latest reported readiness level, so the segments sum to the country's total.",
      data: [
        { country: "Kenya", total: 189, irl_11: 2, irl_12: 2, irl_13: 15, irl_14: 17, irl_15: 24, irl_16: 14, irl_17: 23, irl_18: 37, irl_19: 23, irl_20: 31, irl_none: 1 },
        { country: "Ethiopia", total: 130, irl_11: 1, irl_12: 2, irl_13: 8, irl_14: 8, irl_15: 11, irl_16: 12, irl_17: 18, irl_18: 21, irl_19: 15, irl_20: 34, irl_none: 0 },
        { country: "India", total: 118, irl_11: 3, irl_12: 3, irl_13: 4, irl_14: 13, irl_15: 11, irl_16: 14, irl_17: 13, irl_18: 21, irl_19: 14, irl_20: 22, irl_none: 0 },
        { country: "Nigeria", total: 102, irl_11: 1, irl_12: 6, irl_13: 7, irl_14: 15, irl_15: 17, irl_16: 4, irl_17: 7, irl_18: 15, irl_19: 4, irl_20: 26, irl_none: 0 },
        { country: "Tanzania, United Republic", total: 83, irl_11: 2, irl_12: 2, irl_13: 3, irl_14: 6, irl_15: 10, irl_16: 4, irl_17: 10, irl_18: 18, irl_19: 9, irl_20: 19, irl_none: 0 },
        { country: "Bangladesh", total: 78, irl_13: 4, irl_14: 6, irl_15: 5, irl_16: 5, irl_17: 11, irl_18: 11, irl_19: 18, irl_20: 18, irl_11: 0, irl_12: 0, irl_none: 0 },
        { country: "The Socialist Republic of Viet Nam", total: 76, irl_13: 9, irl_14: 9, irl_15: 10, irl_16: 4, irl_17: 9, irl_18: 10, irl_19: 14, irl_20: 11, irl_11: 0, irl_12: 0, irl_none: 0 },
        { country: "Mali", total: 72, irl_12: 1, irl_13: 2, irl_14: 8, irl_15: 12, irl_16: 1, irl_17: 9, irl_18: 14, irl_19: 11, irl_20: 13, irl_none: 1, irl_11: 0 },
        { country: "Zambia", total: 64, irl_12: 1, irl_13: 1, irl_14: 4, irl_15: 9, irl_16: 2, irl_17: 5, irl_18: 6, irl_19: 15, irl_20: 21, irl_11: 0, irl_none: 0 },
        { country: "Uganda", total: 61, irl_12: 1, irl_13: 2, irl_14: 7, irl_15: 8, irl_16: 7, irl_17: 10, irl_18: 7, irl_19: 9, irl_20: 10, irl_11: 0, irl_none: 0 },
      ],
      series: [
        { key: "irl_11", label: "Idea" },
        { key: "irl_12", label: "Basic Research" },
        { key: "irl_13", label: "Formulation" },
        { key: "irl_14", label: "Proof of Concept" },
        { key: "irl_15", label: "Controlled Testing" },
        { key: "irl_16", label: "Model/Early Prototype" },
        { key: "irl_17", label: "Semi-Controlled Testing" },
        { key: "irl_18", label: "Prototype" },
        { key: "irl_19", label: "Uncontrolled Testing" },
        { key: "irl_20", label: "Proven Innovation" },
        { key: "irl_none", label: "Not reported", color: "#8A8A8A" },
      ],
      xAxisKey: 'country',
    },
    irl_distribution: {
      chartType: 'bar',
      title: 'Innovation Readiness Levels',
      description: 'Distribution of innovations across IRL 0-9 scale',
      data: [
        { level: 'Idea', count: 83 },
        { level: 'Basic Research', count: 191 },
        { level: 'Formulation', count: 367 },
        { level: 'Proof of Concept', count: 443 },
        { level: 'Controlled Testing', count: 558 },
        { level: 'Model/Prototype', count: 453 },
        { level: 'Semi-Controlled', count: 617 },
        { level: 'Prototype', count: 634 },
        { level: 'Uncontrolled Testing', count: 531 },
        { level: 'Proven Innovation', count: 752 },
      ],
      series: [{ key: 'count', label: 'Innovations', color: '#7AB800' }],
      xAxisKey: 'level',
    },
    // F1/F14: portfolio entities labelled era-aware (code — short name), the
    // shape the backend now returns for the `top_initiatives` chart key.
    top_initiatives: {
      chartType: 'horizontalBar',
      title: 'Top 10 Science Programs by Innovations',
      description:
        'CGIAR portfolio entities contributing the most Innovation Developments, ranked by distinct result code · Programs & Accelerators (2025+)',
      data: [
        { entity: 'SP09 — Scaling for Impact', code: 'SP09', era: 'Programs & Accelerators (2025+)', count: 224 },
        { entity: 'SP01 — Breeding for Tomorrow', code: 'SP01', era: 'Programs & Accelerators (2025+)', count: 195 },
        { entity: 'SP03 — Sustainable Animal and Aquatic Foods', code: 'SP03', era: 'Programs & Accelerators (2025+)', count: 160 },
        { entity: 'SP02 — Sustainable Farming', code: 'SP02', era: 'Programs & Accelerators (2025+)', count: 148 },
        { entity: 'SP06 — Climate Action', code: 'SP06', era: 'Programs & Accelerators (2025+)', count: 135 },
        { entity: 'SP12 — Digital Transformation', code: 'SP12', era: 'Programs & Accelerators (2025+)', count: 85 },
        { entity: 'SP04 — Multifunctional Landscapes', code: 'SP04', era: 'Programs & Accelerators (2025+)', count: 79 },
        { entity: 'SP05 — Better Diets and Nutrition', code: 'SP05', era: 'Programs & Accelerators (2025+)', count: 43 },
        { entity: 'SP07 — Policy Innovations', code: 'SP07', era: 'Programs & Accelerators (2025+)', count: 39 },
        { entity: 'SP13 — Genebank', code: 'SP13', era: 'Programs & Accelerators (2025+)', count: 32 },
      ],
      series: [{ key: 'count', label: 'Innovations', color: '#E37222' }],
      xAxisKey: 'entity',
    },
  },
  last_updated: new Date().toISOString(),
};
