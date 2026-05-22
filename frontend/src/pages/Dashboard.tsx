import { Sprout, Globe2, Database, TrendingUp, MessageSquare, Bot, AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { dashboardService } from '../services/dashboard';
import { mockDashboardStats, mockActivityData } from '../lib/mockData';
import StatsCard from '../components/dashboard/StatsCard';
import ActivityChart from '../components/dashboard/ActivityChart';
import GlassCard from '../components/common/GlassCard';
import Badge from '../components/common/Badge';
import type { DashboardStats, ActivityDataPoint } from '../lib/types-extended';

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: stats, isLive: statsLive } = useApi<DashboardStats>(
    () => dashboardService.getStats(),
    mockDashboardStats,
    { interval: 30000 }
  );
  const { data: activity } = useApi<ActivityDataPoint[]>(
    () => dashboardService.getActivity(),
    mockActivityData
  );

  return (
    <div className="max-w-screen-xl mx-auto p-6 space-y-6">
      {/* Offline banner */}
      {!statsLive && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-amber-500/30 bg-amber-500/10">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-amber-500">Dashboard showing cached data</p>
            <p className="text-xs text-amber-500/70 mt-0.5">
              Unable to reach the backend. The statistics below are from the last successful fetch or defaults.
            </p>
          </div>
          <Badge variant="warning">Offline</Badge>
        </div>
      )}

      {/* Title */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Innovation Analytics</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">CGIAR research performance and innovation insights</p>
        </div>
        <Badge variant={statsLive ? 'success' : 'warning'}>{statsLive ? 'Live' : 'Offline'}</Badge>
      </div>

      {/* Stats Grid — mapped to CGIAR context */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatsCard label="Innovations" value={stats.total_sessions} icon={<Sprout className="w-5 h-5" />} color="#427730" />
        <StatsCard label="Results" value={stats.total_messages} icon={<TrendingUp className="w-5 h-5" />} color="#0065BD" />
        <StatsCard label="Regions" value={stats.active_memories} icon={<Globe2 className="w-5 h-5" />} color="#7AB800" />
        <StatsCard label="Queries (7d)" value={stats.recent_activity} icon={<Database className="w-5 h-5" />} color="#E37222" />
        <StatsCard label="Sessions" value={stats.active_connections} icon={<MessageSquare className="w-5 h-5" />} color="#0039A6" />
        <StatsCard label="Agents" value={stats.total_agents} icon={<Bot className="w-5 h-5" />} color="#739600" />
      </div>

      {/* Activity Chart */}
      <ActivityChart data={activity} />

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <GlassCard hover onClick={() => navigate('/chat')}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#427730]/15 flex items-center justify-center">
              <MessageSquare className="w-5 h-5 text-[#427730]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">New Analysis</h3>
              <p className="text-xs text-[var(--text-muted)]">Start a research query</p>
            </div>
          </div>
        </GlassCard>

        <GlassCard hover onClick={() => navigate('/chat')}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#0065BD]/15 flex items-center justify-center">
              <Database className="w-5 h-5 text-[#0065BD]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">Query PRMS</h3>
              <p className="text-xs text-[var(--text-muted)]">Search the results database</p>
            </div>
          </div>
        </GlassCard>

        <GlassCard hover onClick={() => navigate('/agents')}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#7AB800]/15 flex items-center justify-center">
              <Bot className="w-5 h-5 text-[#7AB800]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">Research Agents</h3>
              <p className="text-xs text-[var(--text-muted)]">View specialist CGIAR agents</p>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
