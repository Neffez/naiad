import { describe, it, expect } from 'vitest'
import type { ConfigDoc } from '../api/client'
import { paletteColor, resolveSeqColor, SEQUENCE_PALETTE } from './sequenceColors'

function makeConfig(opts: {
  enabled: boolean
  colors: Record<string, ConfigDoc['sequences'][string]['color']>
}): Pick<ConfigDoc, 'sequences' | 'sequence_colors_enabled'> {
  const sequences = Object.fromEntries(
    Object.entries(opts.colors).map(([id, color]) => [id, { color } as ConfigDoc['sequences'][string]]),
  )
  return { sequence_colors_enabled: opts.enabled, sequences }
}

describe('paletteColor', () => {
  it('maps a known color key to its hex value', () => {
    expect(paletteColor('green')).toBe(SEQUENCE_PALETTE.green)
    expect(paletteColor('purple')).toBe(SEQUENCE_PALETTE.purple)
  })

  it('falls back to the neutral default for null/unknown keys', () => {
    expect(paletteColor(null)).toBe('var(--n-teal-500)')
    expect(paletteColor('nonsense')).toBe('var(--n-teal-500)')
  })
})

describe('resolveSeqColor', () => {
  it('returns the configured color when colors are enabled', () => {
    const config = makeConfig({ enabled: true, colors: { rasen: 'green' } })
    expect(resolveSeqColor(config, 'rasen')).toBe(SEQUENCE_PALETTE.green)
  })

  it('returns the neutral default when enabled but no color chosen', () => {
    const config = makeConfig({ enabled: true, colors: { rasen: null } })
    expect(resolveSeqColor(config, 'rasen')).toBe('var(--n-teal-500)')
  })

  it('returns null when colors are globally disabled', () => {
    const config = makeConfig({ enabled: false, colors: { rasen: 'green' } })
    expect(resolveSeqColor(config, 'rasen')).toBeNull()
  })

  it('returns null when config is not loaded', () => {
    expect(resolveSeqColor(undefined, 'rasen')).toBeNull()
  })
})
