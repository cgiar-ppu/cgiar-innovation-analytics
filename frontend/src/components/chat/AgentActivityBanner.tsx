import { useState, useEffect } from 'react'
import { Zap } from 'lucide-react'

const AGENT_NAMES: Record<string, { label: string; color: string }> = {
  data_analysis: { label: 'Data Analysis', color: 'text-blue-500' },
  visualization_reporting: { label: 'Visualization', color: 'text-emerald-500' },
  research_methodology: { label: 'Research Methodology', color: 'text-violet-500' },
  code_automation: { label: 'Code & Automation', color: 'text-orange-500' },
  computer_use: { label: 'Desktop Automation', color: 'text-slate-400' },
}

interface Props {
  agentName: string
  status: 'started' | 'completed'
}

export function AgentActivityBanner({ agentName, status }: Props) {
  const [elapsed, setElapsed] = useState(0)
  const agentInfo = AGENT_NAMES[agentName] || { label: agentName, color: 'text-accent' }

  useEffect(() => {
    if (status !== 'started') return
    const start = Date.now()
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [status])

  if (status === 'completed') {
    return (
      <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl glass border border-success/20 animate-fade-in-up">
        <div className="w-2 h-2 rounded-full bg-success" />
        <span className="text-xs font-medium text-success">{agentInfo.label}</span>
        <span className="text-xs text-text-muted">completed</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl glass border border-accent/20 animate-fade-in-up animate-glow-pulse">
      <div className="relative flex-shrink-0">
        <div className="w-2 h-2 bg-accent rounded-full" />
        <div className="absolute inset-0 w-2 h-2 bg-accent rounded-full animate-ping" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${agentInfo.color}`}>{agentInfo.label}</span>
          <span className="text-xs text-text-muted">is working...</span>
          {elapsed > 0 && (
            <span className="text-xs text-text-muted font-mono">{elapsed}s</span>
          )}
        </div>
      </div>
      <Zap size={12} className="text-accent animate-pulse" />
    </div>
  )
}
