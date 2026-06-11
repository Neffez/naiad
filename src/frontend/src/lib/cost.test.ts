import { describe, expect, it } from 'vitest'
import { formatWaterCost, waterCostEur } from './cost'

describe('waterCostEur', () => {
  it('converts liters to cost via the m³ price', () => {
    expect(waterCostEur(1000, 2.5)).toBe(2.5)
    expect(waterCostEur(250, 4)).toBe(1)
  })

  it('returns null when no price is configured (0 disables cost display)', () => {
    expect(waterCostEur(1000, 0)).toBeNull()
    expect(waterCostEur(1000, undefined)).toBeNull()
  })

  it('returns null for non-finite liters', () => {
    expect(waterCostEur(Number.NaN, 2)).toBeNull()
  })
})

describe('formatWaterCost', () => {
  it('formats as EUR currency in the given locale', () => {
    expect(formatWaterCost(1000, 2.5, 'en')).toBe('€2.50')
    // The locale separates with a non-breaking space — match loosely.
    const de = formatWaterCost(1000, 2.5, 'de')
    expect(de).toContain('2,50')
    expect(de).toContain('€')
  })

  it('returns null when cost display is disabled', () => {
    expect(formatWaterCost(1000, 0, 'de')).toBeNull()
  })
})
