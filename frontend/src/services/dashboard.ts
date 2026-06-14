import { api } from '../lib/api';
import type { DashboardStats, ActivityDataPoint, PRMSDashboardData } from '../lib/types-extended';

export const dashboardService = {
  async getStats(): Promise<DashboardStats> {
    const data = await api.get<{
      stats?: Array<{ label: string; value: number }>;
      active_connections?: number;
      agent_count?: number;
    }>('/api/dashboard/stats');
    // The API returns { stats: [...], agent_count, active_connections }
    // Map to the DashboardStats interface expected by the frontend
    if (data.stats && Array.isArray(data.stats)) {
      const lookup = (label: string) =>
        data.stats!.find((s) => s.label === label)?.value ?? 0;
      return {
        total_sessions: lookup('Sessions Total'),
        total_messages: lookup('Messages'),
        active_memories: lookup('Memories Stored'),
        recent_activity: lookup('Recent Activity (7d)'),
        active_connections: data.active_connections ?? 0,
        total_agents: data.agent_count ?? 5,
      };
    }
    return data as unknown as DashboardStats;
  },

  async getActivity(days = 7): Promise<ActivityDataPoint[]> {
    const data = await api.get<{ activity?: ActivityDataPoint[] } | ActivityDataPoint[]>(
      `/api/dashboard/activity?days=${days}`
    );
    // The API returns { activity: [...] } — unwrap the array
    return (data as { activity?: ActivityDataPoint[] }).activity ?? (data as ActivityDataPoint[]);
  },

  async getPRMSStats(year?: number | null): Promise<PRMSDashboardData> {
    const qs = year ? `?year=${year}` : '';
    return api.get<PRMSDashboardData>(`/api/dashboard/prms-stats${qs}`);
  },
};
