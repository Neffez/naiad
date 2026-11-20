import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NumberField } from './NumberField'

describe('NumberField', () => {
  it('commits on Enter without triggering the surrounding form submit', () => {
    // Implicit submit would run before the committed value re-renders the
    // parent, so the form would submit the previous value.
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    const onChange = vi.fn()
    render(
      <form onSubmit={onSubmit}>
        <NumberField value="4" allowEmpty onChange={onChange} aria-label="hours" />
        <button type="submit">go</button>
      </form>,
    )
    const input = screen.getByLabelText('hours')
    fireEvent.change(input, { target: { value: '6' } })
    // jsdom does not perform implicit submission itself, so assert the default
    // action (which is what triggers it in a browser) was cancelled.
    const notCancelled = fireEvent.keyDown(input, { key: 'Enter' })

    expect(notCancelled).toBe(false)
    expect(onChange).toHaveBeenCalledWith('6')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('clamps to min/max on commit', () => {
    const onChange = vi.fn()
    render(<NumberField value={5} min={1} max={10} onChange={onChange} aria-label="n" />)
    const input = screen.getByLabelText('n')
    fireEvent.change(input, { target: { value: '42' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenCalledWith(10)
  })
})
