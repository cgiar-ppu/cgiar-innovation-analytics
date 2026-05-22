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
      className="glass rounded-xl border border-[var(--border)] p-5"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-[var(--text-muted)] mb-1">{label}</p>
          <p className="text-3xl font-bold text-[var(--text)]">
            {displayed.toLocaleString()}{suffix}
          </p>
        </div>
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${color}20` }}
        >
          <div style={{ color }}>{icon}</div>
        </div>
      </div>
    </motion.div>
  );
}
