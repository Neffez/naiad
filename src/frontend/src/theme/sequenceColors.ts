// Data-driven sequence accent colors. CLAUDE.md permits hex for sequence accents;
// this is the single source of truth (previously duplicated across four files).
const SEQUENCE_COLORS: Record<string, string> = {
  beete: '#7fc8a8',
  rasen: '#7fc8a8',
  hochbeet: '#c8a87f',
  hecke: '#a87fc8',
  lichtschacht: '#8a9ea6',
  topf: '#8a9ea6',
}

export function seqColor(id: string, fallback = 'var(--n-teal-500)'): string {
  for (const [key, color] of Object.entries(SEQUENCE_COLORS)) {
    if (id.toLowerCase().includes(key)) return color
  }
  return fallback
}
