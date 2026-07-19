/**
 * @file UserMenu.tsx
 * @module components/layout
 *
 * QA round-1 Finding 2 (LOW): the auth store's `logout()` existed but nothing
 * in the UI called it — there was no way to sign out short of clearing
 * localStorage by hand. This adds a small, unobtrusive icon-button in the
 * TopBar that shows the signed-in user's email and a "Sign out" action.
 *
 * Mirrors the ModelSelector dropdown pattern (@radix-ui/react-dropdown-menu +
 * the same glass-strong / var(--*) styling already used across the TopBar).
 * Only rendered when a real user is signed in (dev-bypass mode has no
 * session to sign out of, so the button is hidden then).
 */

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { User, LogOut } from 'lucide-react';
import { useAuthStore } from '../../stores/auth';

export function UserMenu() {
  const user = useAuthStore((s) => s.user);
  const authRequired = useAuthStore((s) => s.authRequired);
  const logout = useAuthStore((s) => s.logout);

  // Dev-bypass mode (no login enforced) — nothing meaningful to sign out of.
  if (!authRequired || !user) return null;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="p-2 rounded-xl hover:bg-[var(--surface-2)] transition-all text-[var(--text-muted)]
            hover:text-[var(--text)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]
            data-[state=open]:text-[var(--text)] data-[state=open]:bg-[var(--surface-2)]"
          title={user.email}
          aria-label="Account menu"
        >
          <User className="w-4 h-4" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="min-w-[220px] rounded-xl glass-strong border border-[var(--border)]
            shadow-xl z-50 overflow-hidden py-1"
          sideOffset={8}
          align="end"
        >
          <div className="px-3 py-2 border-b border-[var(--border)]">
            <p className="text-sm font-medium text-[var(--text)] truncate">{user.name || user.email}</p>
            <p className="text-xs text-[var(--text-muted)] truncate">{user.email}</p>
          </div>

          <DropdownMenu.Item
            onSelect={() => logout()}
            data-testid="logout-menu-item"
            className="flex items-center gap-2.5 px-3 py-2.5 text-sm cursor-pointer outline-none
              transition-colors text-[var(--danger,#dc2626)] hover:bg-[var(--surface-2)]
              data-[highlighted]:bg-[var(--surface-2)]"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span>Sign out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
