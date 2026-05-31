import { describe, it, expect } from 'vitest'
import { seqColor } from './sequenceColors'

describe('seqColor', () => {
  it('maps a known sequence id to its accent color', () => {
    expect(seqColor('rasen')).toBe('#7fc8a8')
    expect(seqColor('hochbeet')).toBe('#c8a87f')
    expect(seqColor('hecke')).toBe('#a87fc8')
  })

  it('matches case-insensitively and on substrings', () => {
    expect(seqColor('RASEN_vorne')).toBe('#7fc8a8')
    expect(seqColor('garten-hecke-2')).toBe('#a87fc8')
  })

  it('falls back to the default token for unknown ids', () => {
    expect(seqColor('unknown')).toBe('var(--n-teal-500)')
  })

  it('honours a custom fallback', () => {
    expect(seqColor('unknown', '#000000')).toBe('#000000')
  })
})
