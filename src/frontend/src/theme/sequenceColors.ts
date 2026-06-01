// Data-driven sequence accent colors. CLAUDE.md permits hex for sequence accents;
// this is the single source of truth for the palette behind each color key.
// The colored bar on a sequence card is configured in the Config editor: a global
// on/off switch plus a per-sequence choice between the six palette colors.
import type { ConfigDoc } from '../api/client'

export const SEQUENCE_COLOR_KEYS = ['green', 'sand', 'purple', 'slate', 'blue', 'rose'] as const
export type SequenceColorKey = (typeof SEQUENCE_COLOR_KEYS)[number]

export const SEQUENCE_PALETTE: Record<SequenceColorKey, string> = {
  green: '#7fc8a8',
  sand: '#c8a87f',
  purple: '#a87fc8',
  slate: '#8a9ea6',
  blue: '#7fa8c8',
  rose: '#c87f9e',
}

// Neutral bar shown when colors are enabled but a sequence has no explicit choice.
const DEFAULT_COLOR = 'var(--n-teal-500)'

/** Map a stored color key to its hex value, falling back to the neutral default. */
export function paletteColor(key: SequenceColorKey | string | null | undefined): string {
  if (key && key in SEQUENCE_PALETTE) return SEQUENCE_PALETTE[key as SequenceColorKey]
  return DEFAULT_COLOR
}

type ColorConfig = Pick<ConfigDoc, 'sequences' | 'sequence_colors_enabled'> | undefined

/**
 * Resolve the accent-bar color for a sequence, honoring the global toggle.
 * Returns null when colored bars are globally disabled (or config isn't loaded
 * yet) — callers should render no bar in that case.
 */
export function resolveSeqColor(config: ColorConfig, sequenceId: string): string | null {
  if (!config || !config.sequence_colors_enabled) return null
  return paletteColor(config.sequences[sequenceId]?.color)
}
