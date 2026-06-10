import { describe, expect, it } from 'vitest'
import de from './locales/de.json'
import en from './locales/en.json'

// Both locales must expose exactly the same key set: a key present in only one
// of them silently falls back (or renders the raw key) in the other language —
// exactly the bug class where the English dashboard once showed
// "dashboard.zones" because en.json had named the key differently.
function flatKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return value !== null && typeof value === 'object'
      ? flatKeys(value as Record<string, unknown>, path)
      : [path]
  })
}

describe('locale parity', () => {
  it('de and en define exactly the same keys', () => {
    const deKeys = flatKeys(de).sort()
    const enKeys = flatKeys(en).sort()
    const onlyDe = deKeys.filter((k) => !enKeys.includes(k))
    const onlyEn = enKeys.filter((k) => !deKeys.includes(k))
    expect({ onlyDe, onlyEn }).toEqual({ onlyDe: [], onlyEn: [] })
  })

  it('no message is left empty', () => {
    for (const [locale, data] of [['de', de], ['en', en]] as const) {
      const empty = flatKeys(data).filter((k) => {
        const value = k.split('.').reduce<unknown>((o, part) => (o as Record<string, unknown>)[part], data)
        return typeof value === 'string' && value.trim() === ''
      })
      expect(empty, `${locale} has empty messages`).toEqual([])
    }
  })
})
