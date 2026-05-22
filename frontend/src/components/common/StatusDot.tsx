interface StatusDotProps {
  status: 'active' | 'inactive' | 'running' | 'error';
  size?: 'sm' | 'md';
  pulse?: boolean;
}

const COLORS = {
  active: 'bg-[var(--success)]',
  inactive: 'bg-[var(--text-muted)]',
  running: 'bg-[var(--accent)]',
  error: 'bg-[var(--danger)]',
};

export default function StatusDot({ status, size = 'sm', pulse = false }: StatusDotProps) {
  const s = size === 'sm' ? 'w-2 h-2' : 'w-3 h-3';
  return (
    <span className="relative inline-flex">
      <span className={`${s} rounded-full ${COLORS[status]}`} />
      {pulse && <span className={`absolute inset-0 ${s} rounded-full ${COLORS[status]} animate-ping opacity-50`} />}
    </span>
  );
}
