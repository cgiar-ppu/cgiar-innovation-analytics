import { type ReactNode, useEffect, useState } from 'react';
import { motion } from 'framer-motion';

interface StatsCardProps {
  label: string;
  value: number;
  icon: ReactNode;
  color?: string;
  suffix?: string;
}

export default function StatsCard({ label, value, icon, color = 'var(--accent)', suffix = '' }: StatsCardProps) {
  const [displayed, setDisplayed] = useState(0);

  useEffect(() => {
    if (value === 0) { setDisplayed(0); return; }
    const duration = 600;
    const steps = 30;
    const increment = value / steps;
    let current = 0;
    const timer = setInterval(() => {
      current += increment;
      if (current >= value) {
        setDisplayed(value);
        clearInterval(timer);
      } else {
        setDisplayed(Math.floor(current));
      }
    }, duration / steps);
    return () => clearInterval(timer);
  }, [value]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[var(--surface-solid)] rounded-xl border border-[var(--border)] p-5 transition-shadow hover:shadow-lg"
      style={{ borderLeftWidth: '4px', borderLeftColor: color }}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <div style={{ color }} className="opacity-70">{icon}</div>
            <p className="text-sm font-medium text-[var(--text-muted)]">{label}</p>
          </div>
          <p className="text-3xl font-bold text-[var(--text)]">
            {displayed.toLocaleString()}{suffix}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
