import { useEffect, useMemo, useRef, useState } from 'react';
import { Sprout, TrendingUp, Lightbulb, BookOpen, MessageSquare, Database, Bot, AlertTriangle, RefreshCw, Info } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { dashboardService } from '../services/dashboard';
import StatsCard from '../components/dashboard/StatsCard';
import YearMultiSelect, { yearsLabel } from '../components/dashboard/YearMultiSelect';
import FilterMultiSelect, { type FilterOption } from '../components/dashboard/FilterMultiSelect';
import { aboutFiguresTopic, bilateralTopic, scopeTopic } from '../components/dashboard/dashboardInfo';
import Badge from '../components/common/Badge';
import { InfoPopover } from '../components/common/InfoPopover';
import { InteractiveChart } from '../components/chat/InteractiveChart';
import type { PRMSDashboardData, PRMSDashboardFilterOptions } from '../lib/types-extended';
import { useIsAdmin } from '../stores/appConfig';

// Reporting-year selection (F7). An empty array means the all-years portfolio
// view; one or more years request the alive-in-ANY-of union for those years
// (deduped by result code server-side, so a multi-year total is the UNION of
// the single-year sets and NOT their sum). Default: 2025.
const DEFAULT_YEARS: number[] = [2025];

/** "1,185" for a number, "—" for a KPI the backend could not compute. */
const fmt = (n: number | null | undefined): string =>
  typeof n === 'number' ? n.toLocaleString() : '—';

export default function Dashboard() {
  const navigate = useNavigate();
  // The specialist-agents page is administrator-only (Lane E); researchers
  // reach specialists through the persona picker in a new chat (QA-4 D6).
  const isAdmin = useIsAdmin();

  const [selectedYears, setSelectedYears] = useState<number[]>(DEFAULT_YEARS);
  // CGIAR Centre + Program/Accelerator filters (Marc Schut, 2026-10-08). Empty =
  // no filter. A result is in scope when a selected centre/program LEADS OR
  // CONTRIBUTES TO it; union within a filter, AND with the years.
  const [selectedCentres, setSelectedCentres] = useState<string[]>([]);
  const [selectedPrograms, setSelectedPrograms] = useState<string[]>([]);
  // Keep the latest selection available to the (memoized) fetcher, so the
  // 60-second "Live" refresh and the Refresh button use the same filters.
  const yearsRef = useRef<number[]>(selectedYears);
  yearsRef.current = selectedYears;
  const entityRef = useRef({ centers: selectedCentres, programs: selectedPrograms });
  entityRef.current = { centers: selectedCentres, programs: selectedPrograms };

  // Dropdown options (centres; programs grouped by portfolio era). Loaded once.
  const [filterOptions, setFilterOptions] = useState<PRMSDashboardFilterOptions | null>(null);
  useEffect(() => {
    let alive = true;
    dashboardService
      .getFilterOptions()
      .then((o) => {
        if (alive) setFilterOptions(o);
      })
      .catch(() => {
        /* dropdowns stay disabled; the year filter keeps working */
      });
    return () => {
      alive = false;
    };
  }, []);
  const centreOptions = useMemo<FilterOption[]>(
    () => (filterOptions?.centers ?? []).map((c) => ({ value: c.code, short: c.acronym, label: c.label })),
    [filterOptions]
  );
  const programOptions = useMemo<FilterOption[]>(
    () =>
      (filterOptions?.programs ?? []).map((p) => ({ value: p.code, short: p.code, label: p.label, group: p.era })),
    [filterOptions]
  );

  // No fallback data (L2-13 / L4-02): until the backend answers, the page shows
  // a skeleton; if it cannot answer, a "data unavailable" state. The dashboard
  // never shows numbers the backend did not produce.
  const { data: prmsData, isLive, refetch, loading, lastSuccessAt } = useApi<PRMSDashboardData | null>(
    () => dashboardService.getPRMSStats(yearsRef.current, entityRef.current),
    null,
    { interval: 60000 }
  );

  // Re-fetch whenever the user changes the year, centre or program filter.
  const didMount = useRef(false);
  useEffect(() => {
    if (!didMount.current) {
      didMount.current = true;
      return;
    }
    refetch();
  }, [selectedYears, selectedCentres, selectedPrograms, refetch]);

  const controls = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {/* Year filter — "All years" + multiselect (F7) */}
      <YearMultiSelect value={selectedYears} onChange={setSelectedYears} disabled={loading} />
      {/* Centre + Program/Accelerator filters — lead OR contribute */}
      <FilterMultiSelect
        name="Centres"
        allLabel="All centres"
        plural="centres"
        options={centreOptions}
        value={selectedCentres}
        onChange={setSelectedCentres}
        disabled={loading}
        testId="dashboard-centre"
        menuWidth="w-96"
      />
      <FilterMultiSelect
        name="Programs"
        allLabel="All programs"
        plural="programs"
        options={programOptions}
        value={selectedPrograms}
        onChange={setSelectedPrograms}
        disabled={loading}
        testId="dashboard-program"
        menuWidth="w-96"
      />
      <InfoPopover topic={scopeTopic(prmsData)} align="right" />
      <button
        onClick={refetch}
        disabled={loading}
        className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        Refresh
      </button>
      {prmsData && <Badge variant={isLive ? 'success' : 'warning'}>{isLive ? 'Live' : 'Not refreshed'}</Badge>}
    </div>
  );

  if (!prmsData) {
    return (
      <div className="max-w-screen-xl mx-auto p-6 space-y-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <h1 className="text-2xl font-bold text-[var(--text)] font-serif">Innovation Analytics</h1>
            <InfoPopover topic={aboutFiguresTopic(null)} size="md" />
          </div>
          {controls}
        </div>
        {loading ? (
          <div data-testid="dashboard-loading" aria-busy="true" aria-label="Loading dashboard figures" className="space-y-6">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-28 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] animate-pulse" />
              ))}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-72 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] animate-pulse" />
              ))}
            </div>
          </div>
        ) : (
          <div
            data-testid="dashboard-unavailable"
            role="alert"
            className="flex flex-col items-center gap-3 px-6 py-12 rounded-xl border border-amber-500/30 bg-amber-500/10 text-center"
          >
            <AlertTriangle className="w-6 h-6 text-amber-500" />
            <p className="text-sm font-medium text-[var(--text)]">Dashboard data unavailable — try again</p>
            <p className="text-xs text-[var(--text-muted)] max-w-md">
              The figures could not be loaded from the PRMS snapshot just now. Nothing is shown rather than out-of-date or
              placeholder numbers.
            </p>
            <button
              onClick={refetch}
              className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface-2)]"
            >
              <RefreshCw className="w-4 h-4" />
              Try again
            </button>
          </div>
        )}
      </div>
    );
  }

  const kpis = prmsData.kpis;

  // The active selection, stated in words. Prefer the server's own label so the
  // header can never disagree with the numbers underneath it.
  const scopeLabel = prmsData.years_label ?? yearsLabel(selectedYears);
  // Whole scope (years + centre/program filters) for the page header.
  const fullScopeLabel = prmsData.scope_label ?? scopeLabel;
  const entityFilterLabel = prmsData.filters?.label ?? '';
  const eraHint = prmsData.filters?.era_hint ?? '';
  // "CIMMYT or IITA and by SP01" — OR within a filter, AND across filters.
  const anyOf = (names: string[], noun: string) =>
    names.length > 3 ? `any of ${names.length} selected ${noun}` : names.join(' or ');
  const entityWords = [
    anyOf((prmsData.filters?.centers ?? []).map((c) => c.label), 'centres'),
    anyOf((prmsData.filters?.programs ?? []).map((p) => p.label), 'programs'),
  ]
    .filter(Boolean)
    .join(' and by ');
  const shownYears = prmsData.years ?? selectedYears;
  const isAllYears = shownYears.length === 0;

  // Derive the innovation card label + sublabel. Year-scoped views show
  // alive-in-year counts (union across the selected years).
  const innovLabel = isAllYears
    ? 'Innovations (all years)'
    : `Innovations active in ${scopeLabel}`;

  const bilateral = kpis.total_innovations_bilateral;
  const hasBilateral = typeof bilateral === 'number' && bilateral > 0;
  const periodWords = shownYears.length > 1 ? 'these years' : 'this year';
  const innovSublabel = hasBilateral
    ? `${fmt(kpis.total_innovations_w1w2)} W1/W2 + ${fmt(bilateral)} W3/bilateral`
    : bilateral === 0
    ? `W1/W2 pooled — all reporting in ${periodWords}`
    : 'Every innovation in the portfolio, counted once';

  const partial = (prmsData.kpi_errors ?? []).length > 0;

  return (
    <div className="max-w-screen-xl mx-auto p-6 space-y-8">
      {/* Refresh failed: the figures below are REAL, just not re-confirmed. */}
      {!isLive && !loading && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-amber-500/30 bg-amber-500/10" data-testid="dashboard-stale">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-amber-500">Latest refresh failed</p>
            <p className="text-xs text-amber-500/70 mt-0.5">
              Showing the figures last loaded from the backend
              {lastSuccessAt ? ` at ${lastSuccessAt.toLocaleTimeString()}` : ''}. Use Refresh to try again.
            </p>
          </div>
        </div>
      )}
      {partial && (
        <p className="text-xs text-amber-500" data-testid="dashboard-partial">
          Some figures could not be computed just now and are shown as “—”.
        </p>
      )}

      {/* Header with title + refresh button */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-1.5">
            <h1 className="text-2xl font-bold text-[var(--text)] font-serif">Innovation Analytics</h1>
            {/* Source (PRMS Reporting snapshot + dates) and counting method. */}
            <InfoPopover topic={aboutFiguresTopic(prmsData)} size="md" />
          </div>
          {/* L2-01: say what each number is. "Innovations" = Innovation
              Developments (the card below); total_results also counts use and
              packages, so it is labelled as such rather than as innovations. */}
          <p className="text-sm text-[var(--text-muted)] mt-1" data-testid="dashboard-headline">
            CGIAR innovation portfolio · {fullScopeLabel} — {fmt(kpis.total_innovations)} innovations ·{' '}
            {fmt(kpis.total_results)} innovation results (development, use and packages) across{' '}
            {fmt(kpis.countries_covered)} countries
          </p>
          {/* Snapshot provenance — the date is data from the backend, never typed here. */}
          <p className="text-xs text-[var(--text-muted)] mt-0.5" data-testid="dashboard-snapshot">
            Source: CGIAR PRMS Reporting · {prmsData.snapshot?.label ?? 'PRMS snapshot: date unavailable'}
            {prmsData.snapshot?.open_phases?.length
              ? ` · open reporting phase${prmsData.snapshot.open_phases.length > 1 ? 's' : ''} (${prmsData.snapshot.open_phases
                  .map((p) => p.replace(/^\d+\s+/, ''))
                  .join(', ')}) excluded from these figures`
              : ''}
          </p>
        </div>
        {controls}
      </div>

      {/* Centre / Program filter context: what the filter means, and a friendly
          hint when the program era and the years do not overlap. */}
      {entityFilterLabel && (
        <div
          className="flex items-start gap-2 px-4 py-2.5 rounded-xl border border-[#427730]/30 bg-[#427730]/5 text-xs text-[var(--text)]"
          data-testid="dashboard-filter-note"
        >
          <Info className="w-4 h-4 text-[#427730] shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p>
              Showing results <strong>led or contributed to</strong> by {entityWords}. A result linked to several selected
              centres or programs is counted once, so these numbers do not add up across centres or programs.
            </p>
            {eraHint && (
              <p className="text-amber-600 dark:text-amber-400" data-testid="dashboard-era-hint">
                {eraHint}
              </p>
            )}
            {!eraHint && kpis.total_results === 0 && (
              <p className="text-amber-600 dark:text-amber-400" data-testid="dashboard-empty-hint">
                No quality-assured innovation results match this combination of years, centres and programs.
              </p>
            )}
          </div>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          label="Innovation results"
          sublabel="Development + use + packages, counted once each"
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
          info={hasBilateral ? <InfoPopover topic={bilateralTopic(prmsData)} /> : undefined}
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
        <p className="text-sm text-[var(--text-muted)]">
          Computed from the CGIAR PRMS Reporting snapshot · quality-assured results only
          {hasBilateral ? ' · includes W3/bilateral innovations (Center-level QA only — see ⓘ on the Innovations card)' : ''}
        </p>
      </div>

      {/* Charts 2x2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <InteractiveChart data={prmsData.charts.results_by_type} />
        <InteractiveChart data={prmsData.charts.top_countries} />
        <InteractiveChart data={prmsData.charts.irl_distribution} />
        <InteractiveChart data={prmsData.charts.top_initiatives} />
      </div>

      {/* Quick Actions */}
      <div className={`grid grid-cols-1 ${isAdmin ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-4`}>
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

        {isAdmin && (
        <div
          className="bg-[var(--surface-solid)] rounded-xl border border-[var(--border)] p-5 cursor-pointer transition-shadow hover:shadow-lg"
          style={{ borderLeftWidth: '4px', borderLeftColor: '#7AB800' }}
          onClick={() => navigate('/agents')}
          data-testid="quick-action-agents"
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
        )}
      </div>

      {/* Footer: last updated timestamp */}
      <p className="text-xs text-center text-[var(--text-muted)]">
        Source: CGIAR PRMS Reporting · {prmsData.snapshot?.label ?? 'PRMS snapshot: date unavailable'} · figures computed {new Date(prmsData.last_updated).toLocaleString()} | Refreshes every 60 seconds
      </p>
    </div>
  );
}
