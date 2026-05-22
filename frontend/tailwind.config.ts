import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: 'var(--surface)',
          2: 'var(--surface-2)',
          3: 'var(--surface-3)',
          solid: 'var(--surface-solid)',
        },
        border: 'var(--border)',
        'border-hover': 'var(--border-hover)',
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          soft: 'var(--accent-soft)',
          glow: 'var(--accent-glow)',
        },
        'text-primary': 'var(--text)',
        'text-muted': 'var(--text-muted)',
        success: 'var(--green)',
        'success-soft': 'var(--green-soft)',
        warning: 'var(--orange)',
        'warning-soft': 'var(--orange-soft)',
        danger: 'var(--red)',
        'danger-soft': 'var(--red-soft)',
        purple: 'var(--purple)',
        'purple-soft': 'var(--purple-soft)',
        'sidebar-bg': 'var(--sidebar-bg)',
        'input-bg': 'var(--input-bg)',
        gold: 'var(--gold)',
        'gold-soft': 'var(--gold-soft)',
      },
      fontFamily: {
        sans: ['"Source Sans 3"', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Helvetica', 'Arial', 'sans-serif'],
        serif: ['"Merriweather"', 'serif'],
        mono: ['JetBrains Mono', 'Monaco', 'Consolas', 'Courier New', 'monospace'],
      },
      fontSize: {
        base: ['15px', '1.6'],
      },
      maxWidth: {
        chat: '800px',
      },
      width: {
        sidebar: '300px',
      },
      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
      animation: {
        'bounce-dot': 'bounce-dot 1.4s infinite ease-in-out both',
        'fade-in-up': 'fade-in-up 0.35s ease-out',
        'fade-in': 'fade-in 0.3s ease-out',
        'thinking-pulse': 'thinking-pulse 2s ease-in-out infinite',
        'slide-in-left': 'slide-in-left 0.3s ease-out',
        'slide-in-right': 'slide-in-right 0.3s ease-out',
        'scale-in': 'scale-in 0.2s ease-out',
        'glow-pulse': 'glow-pulse 2s ease-in-out infinite',
      },
      keyframes: {
        'bounce-dot': {
          '0%, 80%, 100%': { transform: 'scale(0)' },
          '40%': { transform: 'scale(1)' },
        },
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'thinking-pulse': {
          '0%, 100%': { borderColor: 'var(--purple)', opacity: '0.6' },
          '50%': { borderColor: 'var(--purple)', opacity: '1' },
        },
        'slide-in-left': {
          '0%': { opacity: '0', transform: 'translateX(-12px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'slide-in-right': {
          '0%': { opacity: '0', transform: 'translateX(12px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'glow-pulse': {
          '0%, 100%': { boxShadow: '0 0 8px var(--accent-glow)' },
          '50%': { boxShadow: '0 0 20px var(--accent-glow)' },
        },
      },
    },
  },
  plugins: [typography],
} satisfies Config
