// ─── Agent metadata helpers shared across workflow components ─────────────────

export const ORCHESTRATOR_ID = 'orchestrator';
export const GENERIC_ORCHESTRATOR_ID = 'orchestrator_generic';

export const AGENT_SHORT_DESC: Record<string, string> = {
  orchestrator: 'Full agentic team — routes and delegates across all specialists',
  orchestrator_generic: 'General-purpose orchestrator — delegates to specialist agents',
  data_analysis: 'Statistical analysis, EDA, hypothesis testing',
  visualization_reporting: 'Charts, dashboards, publication-quality figures',
  research_methodology: 'Study design, sampling, experimental design',
  code_automation: 'Data pipelines, ETL, web scraping, scripting',
  computer_use: 'GUI interaction — browsing, clicking, screenshots',
};

export const AGENT_COLOR: Record<string, string> = {
  orchestrator: '#8b5cf6',
  orchestrator_generic: '#6366f1',
  data_analysis: '#3b82f6',
  visualization_reporting: '#8b5cf6',
  research_methodology: '#10b981',
  code_automation: '#f59e0b',
  computer_use: '#ef4444',
};

export function agentColor(id: string): string {
  return AGENT_COLOR[id] ?? '#6b7280';
}

export function agentShortDesc(id: string): string {
  return AGENT_SHORT_DESC[id] ?? '';
}

export function isOrchestrator(id: string): boolean {
  return id === ORCHESTRATOR_ID || id === GENERIC_ORCHESTRATOR_ID;
}

export function statusVariant(s: string): 'success' | 'accent' | 'danger' | 'muted' {
  if (s === 'completed') return 'success';
  if (s === 'running') return 'accent';
  if (s === 'failed') return 'danger';
  return 'muted';
}

// ─── Step status helpers (shared across PipelineStepCard, WorkflowRunPanel,
//     RunDetailView, RunHistoryPanel) ─────────────────────────────────────────

/**
 * Maps a step/run status string to a CSS custom property color value.
 * Accepts both strict union types and plain strings for flexibility.
 */
export function stepStatusColor(status: string): string {
  switch (status) {
    case 'completed': return 'var(--success)';
    case 'running':   return 'var(--accent)';
    case 'failed':    return 'var(--danger)';
    case 'cancelled': return 'var(--warning)';
    default:          return 'var(--text-muted)';
  }
}

/**
 * Maps a step/run status string to a Badge variant.
 * Covers all statuses used across workflow components including 'cancelled'.
 */
export function stepBadgeVariant(status: string): 'success' | 'accent' | 'danger' | 'warning' | 'muted' {
  switch (status) {
    case 'completed': return 'success';
    case 'running':   return 'accent';
    case 'failed':    return 'danger';
    case 'cancelled': return 'warning';
    default:          return 'muted';
  }
}

// ─── Agent display name ──────────────────────────────────────────────────────

/**
 * Converts an agent_id like "data_analysis" to a display name like "Data Analysis".
 */
export function agentDisplayName(id: string): string {
  return id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// ─── Filter tabs ──────────────────────────────────────────────────────────────

export const FILTER_TABS = ['all', 'running', 'completed', 'draft'] as const;
export type FilterStatus = (typeof FILTER_TABS)[number];
