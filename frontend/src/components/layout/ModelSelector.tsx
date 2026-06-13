/**
 * @file ModelSelector.tsx
 * @module components/layout
 *
 * Chat model-selector pill. Lets the user switch the active session between
 * the models exposed by the backend (`config.selectable_models`, e.g.
 * Sonnet 4.6 and Opus 4.8). Selecting a model:
 *   1. optimistically updates the session's model in the sessions store, and
 *   2. sends a `switch_model` frame over the WebSocket so the backend recreates
 *      the session's SDK client under the new model (preserving context).
 *
 * Mirrors the parent Synapsis platform's model pill pattern. The pill is
 * disabled while the agent is busy (you cannot switch mid-response).
 */

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Check, ChevronDown } from 'lucide-react';
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import { useSessionsStore } from '../../stores/sessions';
import { useChatStore } from '../../stores/chat';
import type { AppConfig } from '../../lib/types';

interface Props {
  config: AppConfig | null;
}

export function ModelSelector({ config }: Props) {
  const { send } = useWebSocketContext();
  const activeSessionId = useSessionsStore((s) => s.activeSessionId);
  const sessions = useSessionsStore((s) => s.sessions);
  const setSessionModel = useSessionsStore((s) => s.setSessionModel);
  const isBusy = useChatStore((s) => s.isBusy);

  if (!config) return null;

  const selectableModels = config.selectable_models ?? [];
  const currentModel =
    sessions.find((s) => s.session_id === activeSessionId)?.model || config.model;
  const currentLabel =
    selectableModels.find((m) => m.id === currentModel)?.label ?? currentModel;

  // No active session or no selectable models — show a static badge.
  if (!activeSessionId || selectableModels.length === 0) {
    return (
      <span className="text-[10px] px-2 py-0.5 rounded-full text-[var(--text-muted)]/60 hidden xl:inline-block font-mono border border-[var(--border)]">
        {currentLabel}
      </span>
    );
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          disabled={isBusy}
          className="hidden lg:inline-flex items-center gap-1 text-[11px] px-2.5 py-1
            rounded-full border border-[var(--border)] text-[var(--text-muted)] font-mono
            hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors outline-none
            focus-visible:ring-2 focus-visible:ring-[var(--accent)]
            disabled:opacity-50 disabled:cursor-not-allowed
            data-[state=open]:text-[var(--text)]"
          title={isBusy ? 'Cannot switch model while the agent is working' : 'Switch model for this chat'}
        >
          {currentLabel}
          <ChevronDown className="w-3 h-3 opacity-60" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="min-w-[220px] rounded-xl glass-strong border border-[var(--border)]
            shadow-xl z-50 overflow-hidden py-1"
          sideOffset={8}
          align="end"
        >
          {selectableModels.map(({ id, label }) => {
            const isSelected = id === currentModel;
            return (
              <DropdownMenu.Item
                key={id}
                disabled={isBusy || isSelected}
                onSelect={() => {
                  if (!activeSessionId) return;
                  setSessionModel(activeSessionId, id);
                  send({ type: 'switch_model', model: id });
                }}
                className={`flex items-center gap-3 px-3 py-2.5 text-sm cursor-pointer
                  outline-none transition-colors
                  ${isSelected
                    ? 'text-[var(--accent)] bg-[var(--accent)]/10'
                    : 'text-[var(--text)] hover:bg-[var(--surface-2)]'
                  }
                  data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed
                  data-[highlighted]:bg-[var(--surface-2)]`}
              >
                <span className="flex-1">{label}</span>
                <span className="text-[10px] font-mono text-[var(--text-muted)]">{id}</span>
                {isSelected && <Check className="w-3.5 h-3.5 text-[var(--accent)]" />}
              </DropdownMenu.Item>
            );
          })}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
