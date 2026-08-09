import { useCallback, useMemo, useState } from 'react'
import { RefreshCw, Sprout } from 'lucide-react'
import {
  PROMPT_SUGGESTIONS,
  SUGGESTIONS_SHOWN,
  SUGGESTION_THEMES,
  pickSuggestions,
} from './promptSuggestions'

interface Props {
  onPromptClick: (text: string) => void
}

/**
 * Empty-state screen with example prompts.
 *
 * The examples are SAMPLED from `promptSuggestions.ts` at mount rather than
 * hard-coded, so the screen does not show the same four cards on every load
 * (feedback F10: suggestions were "always the same; want diversity"). A
 * "Shuffle" control lets the user pull a different set without reloading.
 */
export function WelcomeScreen({ onPromptClick }: Props) {
  // `nonce` is bumped by Shuffle; useMemo re-samples when it changes. Sampling
  // in an effect instead would flash the first four cards before swapping.
  const [nonce, setNonce] = useState(0)
  const examples = useMemo(
    // eslint-disable-next-line react-hooks/exhaustive-deps
    () => pickSuggestions(SUGGESTIONS_SHOWN),
    [nonce],
  )

  const shuffle = useCallback(() => setNonce((n) => n + 1), [])

  return (
    <div className="flex flex-col items-center justify-center py-20 animate-fade-in-up">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#427730] to-[#7AB800] flex items-center justify-center mb-5 shadow-lg">
        <Sprout size={28} className="text-white" />
      </div>
      <h2 className="text-2xl font-bold text-text-primary text-center mb-2 tracking-tight font-serif">
        CGIAR Innovation Analytics
      </h2>
      <p className="text-sm text-text-muted text-center max-w-md mb-8 leading-relaxed">
        Explore CGIAR innovations, query the PRMS database, analyze research results, and discover science impact across regions and programmes.
      </p>

      <div className="w-full max-w-2xl flex items-center justify-between mb-3 px-1">
        <span className="text-[11px] uppercase tracking-wide text-text-muted">
          Try one of these
        </span>
        <button
          type="button"
          onClick={shuffle}
          aria-label={`Show a different set of example prompts (${PROMPT_SUGGESTIONS.length} available)`}
          title="Show different examples"
          data-testid="welcome-shuffle"
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-medium text-text-muted hover:text-text-primary hover:bg-surface-2 transition-colors"
        >
          <RefreshCw size={12} aria-hidden="true" />
          Shuffle
        </button>
      </div>

      <div
        className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl"
        data-testid="welcome-suggestions"
      >
        {examples.map((ex) => {
          const theme = SUGGESTION_THEMES[ex.theme]
          return (
            <button
              key={ex.id}
              onClick={() => onPromptClick(ex.prompt)}
              data-testid={`welcome-suggestion-${ex.id}`}
              className="flex flex-col items-start gap-3 p-5 rounded-2xl bg-[var(--surface-solid)] shadow-sm hover:shadow-lg transition-shadow border border-[var(--border)] text-left group"
              style={{ borderLeftWidth: '4px', borderLeftColor: theme.accentColor }}
            >
              <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${theme.gradient} flex items-center justify-center`}>
                <ex.icon size={20} className={theme.iconColor} />
              </div>
              <div>
                <span className="text-sm font-semibold text-text-primary block mb-1">{ex.title}</span>
                <span className="text-xs text-text-muted leading-relaxed">{ex.description}</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
