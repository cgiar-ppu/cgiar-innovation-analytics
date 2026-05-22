import { type ReactNode } from 'react';
import { motion } from 'framer-motion';

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  onClick?: () => void;
  padding?: string;
}

export default function GlassCard({ children, className = '', hover = false, onClick, padding = 'p-5' }: GlassCardProps) {
  const Component = hover ? motion.div : 'div';
  const props = hover
    ? { whileHover: { scale: 1.02, y: -2 }, transition: { type: 'spring', stiffness: 300 } }
    : {};

  return (
    <Component
      {...props}
      onClick={onClick}
      className={`glass rounded-xl border border-[var(--border)] ${padding} ${hover ? 'cursor-pointer glass-hover' : ''} ${className}`}
    >
      {children}
    </Component>
  );
}
