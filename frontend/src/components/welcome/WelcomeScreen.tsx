import { Search, Database, Globe2, TrendingUp, Sprout } from 'lucide-react'

interface Props {
  onPromptClick: (text: string) => void
}

const examples = [
  {
    icon: Search,
    title: 'Innovation Search',
    description: 'Find and explore CGIAR innovations across research centers and regions',
    prompt: 'Show me the most recent CGIAR innovations in climate-smart agriculture in sub-Saharan Africa.',
    gradient: 'from-[#427730]/15 to-[#7AB800]/10',
    iconColor: 'text-[#427730]',
    accentColor: '#427730',
  },
  {
    icon: Database,
    title: 'PRMS Query',
    description: 'Query the Performance & Results Management System database directly',
    prompt: 'Query the PRMS database to show me all results reported under the Resilient Agrifood Systems initiative in 2024.',
    gradient: 'from-[#0065BD]/10 to-[#4da3e8]/10',
    iconColor: 'text-[#0065BD]',
    accentColor: '#0065BD',
  },
  {
    icon: Globe2,
    title: 'Regional Analysis',
    description: 'Analyze research impact and innovation adoption by region or country',
    prompt: 'Analyze CGIAR research results and innovations in South Asia, broken down by country and thematic area.',
    gradient: 'from-[#7AB800]/10 to-[#739600]/10',
    iconColor: 'text-[#7AB800]',
    accentColor: '#7AB800',
  },
  {
    icon: TrendingUp,
    title: 'Impact Assessment',
    description: 'Explore science outcomes, policy influence, and capacity building metrics',
    prompt: 'What are the key impact pathways for CGIAR research in the last 3 years? Show me policy influence and capacity strengthening results.',
    gradient: 'from-[#E37222]/10 to-[#FDC82F]/10',
    iconColor: 'text-[#E37222]',
    accentColor: '#E37222',
  },
]

export function WelcomeScreen({ onPromptClick }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 animate-fade-in-up">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#427730] to-[#7AB800] flex items-center justify-center mb-5 shadow-lg">
        <Sprout size={28} className="text-white" />
      </div>
      <h2 className="text-2xl font-bold text-text-primary text-center mb-2 tracking-tight font-serif">
        CGIAR Innovation Analytics
      </h2>
      <p className="text-sm text-text-muted text-center max-w-md mb-12 leading-relaxed">
        Explore CGIAR innovations, query the PRMS database, analyze research results, and discover science impact across regions and programmes.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl">
        {examples.map((ex) => (
          <button
            key={ex.title}
            onClick={() => onPromptClick(ex.prompt)}
            className="flex flex-col items-start gap-3 p-5 rounded-2xl bg-[var(--surface-solid)] shadow-sm hover:shadow-lg transition-shadow border border-[var(--border)] text-left group"
            style={{ borderLeftWidth: '4px', borderLeftColor: ex.accentColor }}
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
