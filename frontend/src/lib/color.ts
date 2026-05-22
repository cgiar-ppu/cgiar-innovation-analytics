export function colorWithAlpha(color: string | undefined, alpha: number): string {
  if (!color) return `var(--accent)`;
  if (color.startsWith('#')) return `${color}${Math.round(alpha * 255).toString(16).padStart(2, '0')}`;
  if (color.startsWith('hsl(')) {
    return color.replace('hsl(', 'hsla(').replace(')', `, ${alpha})`);
  }
  return color;
}
