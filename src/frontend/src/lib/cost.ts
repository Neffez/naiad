// Water cost derived from tracked liters and the configured price per cubic
// meter (config.water_price_per_m3). A price of 0 (the default) disables cost
// display everywhere — callers render nothing when these return null.

export function waterCostEur(liters: number, pricePerM3: number | undefined): number | null {
  if (!pricePerM3 || pricePerM3 <= 0 || !Number.isFinite(liters)) return null
  return (liters / 1000) * pricePerM3
}

export function formatWaterCost(
  liters: number,
  pricePerM3: number | undefined,
  language: string,
): string | null {
  const cost = waterCostEur(liters, pricePerM3)
  if (cost == null) return null
  return new Intl.NumberFormat(language, { style: 'currency', currency: 'EUR' }).format(cost)
}
