import { type ReactNode } from 'react';
import { motion } from 'framer-motion';

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  onClick?: () => void;
  padding?: string;
  variant?: 'glass' | 'solid';
}

export default function GlassCard({ children, className = '', hover = false, onClick, padding = 'p-5', variant = 'glass' }: GlassCardProps) {
  const Component = hover ? motion.div : 'div';
  const props = hover
    ? { whileHover: { scale: 1.02, y: -2 }, transition: { type: 'spring', stiffness: 300 } }
    : {};

  const baseClass = variant === 'solid'
    ? 'bg-[var(--surface-solid)] shadow-sm'
    : 'glass';

  return (
    <Component
      {...props}
      onClick={onClick}
      className={`${baseClass} rounded-xl border border-[var(--border)] ${padding} ${hover ? 'cursor-pointer glass-hover' : ''} ${className}`}
    >
      {children}
    </Component>
  );
}
