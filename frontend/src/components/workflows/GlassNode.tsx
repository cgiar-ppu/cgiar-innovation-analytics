import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import { CheckCircle2, Loader2, Circle, AlertCircle } from 'lucide-react';

interface GlassNodeData {
  label: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration?: number;
}

const STATUS_CONFIG = {
  pending: { icon: Circle, color: 'var(--text-muted)', border: 'border-dashed border-[var(--border)]' },
  running: { icon: Loader2, color: 'var(--accent)', border: 'border-[var(--accent)]' },
  completed: { icon: CheckCircle2, color: 'var(--success)', border: 'border-[var(--success)]/50' },
  failed: { icon: AlertCircle, color: 'var(--danger)', border: 'border-[var(--danger)]/50' },
};

function GlassNode({ data }: NodeProps<GlassNodeData>) {
  const { label, status, duration } = data;
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;

  return (
    <>
      <Handle type="target" position={Position.Left} className="!bg-[var(--accent)] !w-2 !h-2 !border-0" />
      <div className={`glass rounded-xl border ${config.border} px-4 py-3 min-w-[160px] transition-all`}>
        <div className="flex items-center gap-2">
          <Icon
            className={`w-4 h-4 shrink-0 ${status === 'running' ? 'animate-spin' : ''}`}
            style={{ color: config.color }}
          />
          <span className="text-sm font-medium text-[var(--text)] truncate">{label}</span>
        </div>
        {duration != null && (
          <p className="text-[10px] text-[var(--text-muted)] mt-1 ml-6">
            {(duration / 1000).toFixed(1)}s
          </p>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-[var(--accent)] !w-2 !h-2 !border-0" />
    </>
  );
}

export default memo(GlassNode);
