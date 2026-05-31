import { describe, expect, it } from 'vitest'
import { applyOrder } from './ordering'

interface Item {
  id: string
}

const items: Item[] = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

describe('applyOrder', () => {
  it('returns items unchanged when order is empty', () => {
    expect(applyOrder(items, [])).toEqual(items)
  })

  it('reorders items to match the saved order', () => {
    expect(applyOrder(items, ['c', 'a', 'b'])).toEqual([{ id: 'c' }, { id: 'a' }, { id: 'b' }])
  })

  it('appends items missing from the saved order, keeping their natural order', () => {
    // 'b' is not in the saved order — it should fall to the end after a and c.
    expect(applyOrder(items, ['c', 'a'])).toEqual([{ id: 'c' }, { id: 'a' }, { id: 'b' }])
  })

  it('ignores IDs in the saved order that no longer exist', () => {
    expect(applyOrder(items, ['gone', 'b', 'a', 'c'])).toEqual([{ id: 'b' }, { id: 'a' }, { id: 'c' }])
  })

  it('does not mutate the input array', () => {
    const input = [...items]
    applyOrder(input, ['c', 'b', 'a'])
    expect(input).toEqual(items)
  })
})
