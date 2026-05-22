import { BarChart3, LineChart, FlaskConical, Code2, Sparkles } from 'lucide-react'

interface Props {
  onPromptClick: (text: string) => void
}

const examples = [
  {
    icon: BarChart3,
    title: 'Data Analysis',
    description: 'EDA, hypothesis testing, regression, time series, data wrangling',
    prompt: "I have a CSV with 50,000 rows of customer transactions. Help me explore the data, identify patterns, and run a cohort retention analysis.",
    gradient: 'from-blue-500/10 to-cyan-500/10',
    iconColor: 'text-blue-500',
    borderColor: 'hover:border-blue-500/30',
  },
  {
    icon: LineChart,
    title: 'Visualization',
    description: 'Charts, dashboards, reports, publication-quality figures',
    prompt: 'Create a set of visualizations showing monthly revenue trends, customer segments, and a correlation heatmap from my sales dataset.',
    gradient: 'from-emerald-500/10 to-teal-500/10',
    iconColor: 'text-emerald-500',
    borderColor: 'hover:border-emerald-500/30',
  },
  {
    icon: FlaskConical,
    title: 'Research Design',
    description: 'Study design, sampling, power analysis, experimental methods',
    prompt: 'I need to design an A/B test for a new checkout flow. Help me determine sample size, test duration, and the right statistical approach.',
    gradient: 'from-violet-500/10 to-purple-500/10',
    iconColor: 'text-violet-500',
    borderColor: 'hover:border-violet-500/30',
  },
  {
    icon: Code2,
    title: 'Automation',
    description: 'Data pipelines, ETL, web scraping, API integration, scripting',
    prompt: 'Build a Python script that pulls data from a REST API, transforms it into a clean DataFrame, and exports weekly summary reports as Excel files.',
    gradient: 'from-orange-500/10 to-amber-500/10',
    iconColor: 'text-orange-500',
    borderColor: 'hover:border-orange-500/30',
  },
]

export function WelcomeScreen({ onPromptClick }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 animate-fade-in-up">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] flex items-center justify-center mb-5 shadow-lg">
        <Sparkles size={28} className="text-white" />
      </div>
      <h2 className="text-2xl font-bold text-text-primary text-center mb-2 tracking-tight">
        What can I help you with?
      </h2>
      <p className="text-sm text-text-muted text-center max-w-md mb-12 leading-relaxed">
        Analyze data, build visualizations, design studies, and automate workflows.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl">
        {examples.map((ex) => (
          <button
            key={ex.title}
            onClick={() => onPromptClick(ex.prompt)}
            className={`flex flex-col items-start gap-3 p-5 rounded-2xl glass glass-hover
              border border-border ${ex.borderColor}
              text-left group`}
          >
            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${ex.gradient} flex items-center justify-center`}>
              <ex.icon size={20} className={ex.iconColor} />
            </div>
            <div>
              <span className="text-sm font-semibold text-text-primary block mb-1">{ex.title}</span>
              <span className="text-xs text-text-muted leading-relaxed">{ex.description}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
