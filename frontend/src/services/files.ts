import { api } from '../lib/api';
import { getAuthToken } from '../stores/auth';

export interface FileEntry {
  name: string;
  size: number;
  modified: number;
  is_dir?: boolean;
}

export const filesService = {
  async getFiles(path = ''): Promise<FileEntry[]> {
    const res = await api.get<{ files: FileEntry[] }>(
      `/api/files${path ? `?path=${encodeURIComponent(path)}` : ''}`
    );
    return res.files || [];
  },

  uploadFile(file: File): Promise<{ path: string; size: number }> {
    return api.postForm<{ path: string; size: number }>('/api/upload', file);
  },

  /**
   * `GET /api/files/{path}` requires auth (2026-07-20). This URL is used in
   * a plain `<a href>` (see `pages/Files.tsx`), which can't attach an
   * `Authorization` header, so the JWT is appended as `?token=`.
   */
  downloadUrl(path: string): string {
    const token = getAuthToken();
    const url = `/api/files/${encodeURIComponent(path)}`;
    return token ? `${url}?token=${encodeURIComponent(token)}` : url;
  },
};
