import { api } from '../lib/api';
import type { PRMSDashboardData, PRMSDashboardFilterOptions } from '../lib/types-extended';

/** Optional Centre / Program/Accelerator filters (empty = no filter). */
export interface DashboardEntityFilters {
  /** CGIAR centre codes, e.g. "CENTER-05". */
  centers?: string[];
  /** Program/Accelerator/Initiative official codes, e.g. "SP01", "INIT-11". */
  programs?: string[];
}

export const dashboardService = {
  /**
   * PRMS dashboard slice.
   *
   * `years` is a multiselect: an empty array (or omitted) requests the
   * all-years portfolio view; one or more years request the alive-in-ANY-of
   * union for those years (deduped by result code server-side). Years are sent
   * as repeated `years` params, e.g. `?years=2024&years=2025`.
   *
   * `filters.centers` / `filters.programs` restrict the dashboard to results the
   * selected centres / programs LEAD OR CONTRIBUTE TO (repeated `centers` /
   * `programs` params; union within a filter, AND across filters).
   */
  async getPRMSStats(years?: number[] | null, filters?: DashboardEntityFilters): Promise<PRMSDashboardData> {
    const selected = (years ?? []).filter((y) => Number.isFinite(y));
    const params = [
      ...selected.map((y) => `years=${y}`),
      ...(filters?.centers ?? []).map((c) => `centers=${encodeURIComponent(c)}`),
      ...(filters?.programs ?? []).map((p) => `programs=${encodeURIComponent(p)}`),
    ];
    const qs = params.length ? `?${params.join('&')}` : '';
    return api.get<PRMSDashboardData>(`/api/dashboard/prms-stats${qs}`);
  },

  /** Centres and programs (grouped by portfolio era) the filters offer. */
  async getFilterOptions(): Promise<PRMSDashboardFilterOptions> {
    return api.get<PRMSDashboardFilterOptions>('/api/dashboard/filter-options');
  },
};
