import { api } from '../lib/api';
import type { PRMSDashboardData } from '../lib/types-extended';

export const dashboardService = {
  /**
   * PRMS dashboard slice.
   *
   * `years` is a multiselect: an empty array (or omitted) requests the
   * all-years portfolio view; one or more years request the alive-in-ANY-of
   * union for those years (deduped by result code server-side). Years are sent
   * as repeated `years` params, e.g. `?years=2024&years=2025`.
   */
  async getPRMSStats(years?: number[] | null): Promise<PRMSDashboardData> {
    const selected = (years ?? []).filter((y) => Number.isFinite(y));
    const qs = selected.length
      ? `?${selected.map((y) => `years=${y}`).join('&')}`
      : '';
    return api.get<PRMSDashboardData>(`/api/dashboard/prms-stats${qs}`);
  },
};
