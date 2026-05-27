import { Sprout, Globe2, TrendingUp, Lightbulb, Building2, BookOpen, MessageSquare, Database, Bot, AlertTriangle, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { dashboardService } from '../services/dashboard';
import { mockPRMSDashboard, mockActivityData } from '../lib/mockData';
import StatsCard from '../components/dashboard/StatsCard';
import ActivityChart from '../components/dashboard/ActivityChart';
import Badge from '../components/common/Badge';
import { InteractiveChart } from '../components/chat/InteractiveChart';
import type { PRMSDashboardData, ActivityDataPoint } from '../lib/types-extended';

export default function Dashboard() {
  const navigate = useNavigate();

  const { data: prmsData, isLive, refetch, loading } = useApi<PRMSDashboardData>(
    () => dashboardService.getPRMSStats(),
    mockPRMSDashboard,
    { interval: 60000 }
  );

  const { data: activity } = useApi<ActivityDataPoint[]>(
    () => dashboardService.getActivity(),
    mockActivityData
  );

  const kpis = prmsData.kpis;

  return (
    <div className="max-w-screen-xl mx-auto p-6 space-y-8">
      {/* Offline banner */}
      {!isLive && (
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

      {/* Header with title + refresh button */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)] font-serif">Innovation Analytics</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            CGIAR innovation portfolio — {kpis.total_results.toLocaleString()} innovations across {kpis.countries_covered} countries
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={refetch}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <Badge variant={isLive ? 'success' : 'warning'}>{isLive ? 'Live' : 'Cached'}</Badge>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatsCard
          label="Total Results"
          value={kpis.total_results}
          icon={<TrendingUp className="w-5 h-5" />}
          color="#0065BD"
        />
        <StatsCard
          label="Innovations"
          value={kpis.total_innovations}
          icon={<Sprout className="w-5 h-5" />}
          color="#427730"
        />
        <StatsCard
          label="Innovation Uses"
          value={kpis.innovation_uses}
          icon={<Lightbulb className="w-5 h-5" />}
          color="#E37222"
        />
        <StatsCard
          label="Active Initiatives"
          value={kpis.active_initiatives}
          icon={<Building2 className="w-5 h-5" />}
          color="#7AB800"
        />
        <StatsCard
          label="Countries Covered"
          value={kpis.countries_covered}
          icon={<Globe2 className="w-5 h-5" />}
          color="#0065BD"
        />
        <StatsCard
          label="Innovation Packages"
          value={kpis.innovation_packages}
          icon={<BookOpen className="w-5 h-5" />}
          color="#8B1A4A"
        />
      </div>

      {/* Section header for charts */}
      <div>
        <h2 className="text-lg font-semibold text-[var(--text)] font-serif">Innovation Portfolio Overview</h2>
        <p className="text-sm text-[var(--text-muted)]">Innovation analytics from the PRMS database</p>
      </div>

      {/* Charts 2x2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <InteractiveChart data={prmsData.charts.results_by_type} />
        <InteractiveChart data={prmsData.charts.top_countries} />
        <InteractiveChart data={prmsData.charts.irl_distribution} />
        <InteractiveChart data={prmsData.charts.top_initiatives} />
      </div>

      {/* Platform Activity */}
      <ActivityChart data={activity} />

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          className="bg-[var(--surface-solid)] rounded-xl border border-[var(--border)] p-5 cursor-pointer transition-shadow hover:shadow-lg"
          style={{ borderLeftWidth: '4px', borderLeftColor: '#427730' }}
          onClick={() => navigate('/chat')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#427730]/15 flex items-center justify-center">
              <MessageSquare className="w-5 h-5 text-[#427730]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">New Analysis</h3>
              <p className="text-xs text-[var(--text-muted)]">Start a research query</p>
            </div>
          </div>
        </div>

        <div
          className="bg-[var(--surface-solid)] rounded-xl border border-[var(--border)] p-5 cursor-pointer transition-shadow hover:shadow-lg"
          style={{ borderLeftWidth: '4px', borderLeftColor: '#0065BD' }}
          onClick={() => navigate('/chat')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#0065BD]/15 flex items-center justify-center">
              <Database className="w-5 h-5 text-[#0065BD]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">Query PRMS</h3>
              <p className="text-xs text-[var(--text-muted)]">Search the results database</p>
            </div>
          </div>
        </div>

        <div
          className="bg-[var(--surface-solid)] rounded-xl border border-[var(--border)] p-5 cursor-pointer transition-shadow hover:shadow-lg"
          style={{ borderLeftWidth: '4px', borderLeftColor: '#7AB800' }}
          onClick={() => navigate('/agents')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#7AB800]/15 flex items-center justify-center">
              <Bot className="w-5 h-5 text-[#7AB800]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">Research Agents</h3>
              <p className="text-xs text-[var(--text-muted)]">View specialist CGIAR agents</p>
            </div>
          </div>
        </div>
      </div>

      {/* Footer: last updated timestamp */}
      <p className="text-xs text-center text-[var(--text-muted)]">
        PRMS data as of {new Date(prmsData.last_updated).toLocaleDateString()} | Refreshes every 60 seconds
      </p>
    </div>
  );
}
