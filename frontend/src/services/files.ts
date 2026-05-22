import { api } from '../lib/api';

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

  downloadUrl(path: string): string {
    return `/api/files/${encodeURIComponent(path)}`;
  },
};
