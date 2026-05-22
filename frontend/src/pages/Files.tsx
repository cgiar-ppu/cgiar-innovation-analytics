import { useState, useCallback } from 'react';
import { Upload, Download, FolderOpen, File, FileText, Image, Table, Code, RefreshCw, AlertCircle } from 'lucide-react';
import { motion } from 'framer-motion';
import { useApi } from '../hooks/useApi';
import { filesService, type FileEntry } from '../services/files';
import { mockFiles } from '../lib/mockData';
import GlassCard from '../components/common/GlassCard';
import Badge from '../components/common/Badge';

const FILE_ICONS: Record<string, typeof File> = {
  csv: Table,
  xlsx: Table,
  xls: Table,
  png: Image,
  jpg: Image,
  jpeg: Image,
  svg: Image,
  gif: Image,
  pdf: FileText,
  md: FileText,
  txt: FileText,
  py: Code,
  js: Code,
  ts: Code,
  html: Code,
  json: Code,
};

function getFileIcon(name: string): typeof File {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return FILE_ICONS[ext] ?? File;
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export default function Files() {
  const { data: files, isLive, refetch, loading, error } = useApi<FileEntry[]>(
    () => filesService.getFiles() as Promise<FileEntry[]>,
    mockFiles as FileEntry[]
  );
  const [uploading, setUploading] = useState(false);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await filesService.uploadFile(file);
      refetch();
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }, [refetch]);

  return (
    <div className="max-w-screen-xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Files</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">Browse your workspace files</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={isLive ? 'success' : 'warning'}>{isLive ? 'Live' : 'Cached'}</Badge>
          <button
            onClick={refetch}
            className="p-2 rounded-lg hover:bg-[var(--surface-1)] text-[var(--text-muted)] transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <label className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer">
            <Upload className="w-4 h-4" />
            {uploading ? 'Uploading...' : 'Upload'}
            <input type="file" onChange={handleUpload} className="hidden" disabled={uploading} />
          </label>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <div>
            <p className="font-medium">Failed to load files</p>
            <p className="text-sm opacity-80">{error}</p>
          </div>
          <button onClick={refetch} className="ml-auto px-3 py-1 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-sm">
            Retry
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && !files.length && (
        <GlassCard className="text-center py-12">
          <RefreshCw className="w-8 h-8 text-[var(--text-muted)] mx-auto mb-3 animate-spin" />
          <p className="text-[var(--text-muted)]">Loading files...</p>
        </GlassCard>
      )}

      {/* File Grid */}
      <div className="space-y-1">
        {/* Header row */}
        <div className="grid grid-cols-[1fr_100px_140px_40px] gap-4 px-4 py-2 text-xs font-medium text-[var(--text-muted)] uppercase">
          <span>Name</span>
          <span>Size</span>
          <span>Modified</span>
          <span></span>
        </div>

        {files.map((file, i) => {
          const Icon = file.is_dir ? FolderOpen : getFileIcon(file.name);
          return (
            <motion.div
              key={file.name}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.02 }}
              className="grid grid-cols-[1fr_100px_140px_40px] gap-4 items-center px-4 py-3 rounded-lg hover:bg-[var(--surface-1)] transition-colors group"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Icon className={`w-4 h-4 shrink-0 ${file.is_dir ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`} />
                <span className="text-sm text-[var(--text)] truncate">{file.name}</span>
              </div>
              <span className="text-xs text-[var(--text-muted)]">{formatSize(file.size)}</span>
              <span className="text-xs text-[var(--text-muted)]">
                {new Date(file.modified * 1000).toLocaleDateString()}
              </span>
              {!file.is_dir && (
                <a
                  href={filesService.downloadUrl(file.name)}
                  className="p-1.5 rounded-lg hover:bg-[var(--surface-2)] text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Download"
                >
                  <Download className="w-3.5 h-3.5" />
                </a>
              )}
            </motion.div>
          );
        })}

        {files.length === 0 && (
          <GlassCard className="text-center py-12">
            <FolderOpen className="w-10 h-10 text-[var(--text-muted)] mx-auto mb-3" />
            <p className="text-[var(--text-muted)]">No files in workspace yet</p>
          </GlassCard>
        )}
      </div>
    </div>
  );
}
