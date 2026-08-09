import { useEffect, useRef, useState } from 'react';
import { Sprout, TrendingUp, Lightbulb, BookOpen, MessageSquare, Database, Bot, AlertTriangle, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { dashboardService } from '../services/dashboard';
import { mockPRMSDashboard, mockActivityData } from '../lib/mockData';
import StatsCard from '../components/dashboard/StatsCard';
import ActivityChart from '../components/dashboard/ActivityChart';
import Badge from '../components/common/Badge';
import { InteractiveChart } from '../components/chat/InteractiveChart';
import type { PRMSDashboardData, ActivityDataPoint } from '../lib/types-extended';

// Specific reporting year. The all-years portfolio view has been retired —
// the dashboard always shows a single reporting year (default: 2025).
const YEAR_OPTIONS = ['2025', '2024', '2023', '2022'] as const;
type YearFilter = (typeof YEAR_OPTIONS)[number];
const DEFAULT_YEAR: YearFilter = '2025';

export default function Dashboard() {
  const navigate = useNavigate();

  const [selectedYear, setSelectedYear] = useState<YearFilter>(DEFAULT_YEAR);
  // Keep the latest selectedYear available to the (memoized) fetcher.
  const yearRef = useRef<YearFilter>(selectedYear);
  yearRef.current = selectedYear;

  const { data: prmsData, isLive, refetch, loading } = useApi<PRMSDashboardData>(
    () => dashboardService.getPRMSStats(Number(yearRef.current)),
    mockPRMSDashboard,
    { interval: 60000 }
  );

  // Re-fetch whenever the user changes the year filter.
  const didMount = useRef(false);
  useEffect(() => {
    if (!didMount.current) {
      didMount.current = true;
      return;
    }
    refetch();
  }, [selectedYear, refetch]);

  const { data: activity } = useApi<ActivityDataPoint[]>(
    () => dashboardService.getActivity(),
    mockActivityData
  );

  const kpis = prmsData.kpis;

  // Derive the innovation card label + sublabel. Per-year views show
  // alive-in-year counts.
  const innovLabel = `Innovations active in ${selectedYear}`;

  const innovSublabel =
    kpis.total_innovations_bilateral !== undefined && kpis.total_innovations_bilateral > 0
      ? `${(kpis.total_innovations_w1w2 ?? 0).toLocaleString()} W1/W2 + ${kpis.total_innovations_bilateral.toLocaleString()} bilateral`
      : kpis.total_innovations_bilateral === 0
      ? 'W1/W2 pooled — all reporting in this year'
      : 'Every innovation that reported in this year';

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
            CGIAR innovation portfolio · {selectedYear} — {kpis.total_results.toLocaleString()} innovations across {kpis.countries_covered} countries
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Year filter */}
          <label className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <span className="hidden sm:inline">Year</span>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(e.target.value as YearFilter)}
              disabled={loading}
              className="px-3 py-1.5 text-sm rounded-lg border border-[var(--border)] bg-[var(--surface-solid)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[#427730]/40"
            >
              {YEAR_OPTIONS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          label="Total Results"
          value={kpis.total_results}
          icon={<TrendingUp className="w-5 h-5" />}
          color="#0065BD"
        />
        <StatsCard
          label={innovLabel}
          sublabel={innovSublabel}
          value={kpis.total_innovations}
          icon={<Sprout className="w-5 h-5" />}
          color="#427730"
        />
        <StatsCard
          label="Innovations in use"
          value={kpis.innovation_uses}
          icon={<Lightbulb className="w-5 h-5" />}
          color="#E37222"
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
