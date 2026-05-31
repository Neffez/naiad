/**
 * Reorder a list of identifiable items to match a saved order of IDs.
 *
 * Items whose ID appears in `order` are placed first, in the order given.
 * Any remaining items (e.g. newly added sequences/zones not yet in the saved
 * order) keep their original relative position and are appended at the end.
 */
export function applyOrder<T extends { id: string }>(items: T[], order: string[]): T[] {
  if (order.length === 0) return items
  const rank = new Map(order.map((id, index) => [id, index]))
  const fallback = order.length
  // Array.prototype.sort is stable, so equal-rank items keep their input order.
  return [...items].sort((a, b) => (rank.get(a.id) ?? fallback) - (rank.get(b.id) ?? fallback))
}
