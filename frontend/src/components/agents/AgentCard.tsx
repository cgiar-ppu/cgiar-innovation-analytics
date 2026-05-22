import { Bot, Wrench } from 'lucide-react';
import { motion } from 'framer-motion';
import type { AgentInfo } from '../../lib/types-extended';
import { colorWithAlpha } from '../../lib/color';
import Badge from '../common/Badge';
import StatusDot from '../common/StatusDot';

interface AgentCardProps {
  agent: AgentInfo;
  onClick?: () => void;
  index?: number;
}

export default function AgentCard({ agent, onClick, index = 0 }: AgentCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      whileHover={{ scale: 1.02, y: -4 }}
      onClick={onClick}
      className="glass rounded-xl border border-[var(--border)] p-5 cursor-pointer glass-hover group"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: colorWithAlpha(agent.color, 0.125) }}
        >
          <Bot className="w-5 h-5" style={{ color: agent.color || 'var(--accent)' }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--text)] truncate">{agent.name}</h3>
            <StatusDot status={agent.status === 'active' ? 'active' : 'inactive'} />
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">{agent.model}</p>
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-[var(--text-muted)] mb-3 line-clamp-2">{agent.description}</p>

      {/* Tools */}
      <div className="flex items-center gap-1 flex-wrap">
        <Wrench className="w-3 h-3 text-[var(--text-muted)] mr-1" />
        {agent.tools.slice(0, 4).map(t => (
          <Badge key={t} variant="muted" size="sm">{t}</Badge>
        ))}
        {agent.tools.length > 4 && (
          <Badge variant="muted" size="sm">+{agent.tools.length - 4}</Badge>
        )}
      </div>
    </motion.div>
  );
}
