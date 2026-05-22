interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'accent' | 'muted';
  size?: 'sm' | 'md';
  className?: string;
}

const VARIANTS = {
  default: 'bg-[var(--surface-2)] text-[var(--text)]',
  success: 'bg-[var(--success)]/15 text-[var(--success)]',
  warning: 'bg-[var(--warning)]/15 text-[var(--warning)]',
  danger: 'bg-[var(--danger)]/15 text-[var(--danger)]',
  accent: 'bg-[var(--accent)]/15 text-[var(--accent)]',
  muted: 'bg-[var(--surface-1)] text-[var(--text-muted)]',
};

const SIZES = {
  sm: 'px-1.5 py-0.5 text-[10px]',
  md: 'px-2 py-0.5 text-xs',
};

export default function Badge({ children, variant = 'default', size = 'md', className }: BadgeProps) {
  return (
    <span className={`inline-flex items-center font-medium rounded-full ${VARIANTS[variant]} ${SIZES[size]}${className ? ` ${className}` : ''}`}>
      {children}
    </span>
  );
}
