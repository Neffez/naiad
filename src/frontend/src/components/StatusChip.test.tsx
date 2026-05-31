import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import i18n from '../i18n'
import { StatusChip } from './StatusChip'

function renderChip(status: string) {
  return render(
    <I18nextProvider i18n={i18n}>
      <StatusChip status={status} />
    </I18nextProvider>,
  )
}

describe('StatusChip', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('renders the translated status label', () => {
    renderChip('running')
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('applies the status as a CSS class for styling', () => {
    const { container } = renderChip('paused')
    const chip = container.querySelector('.n-chip')
    expect(chip).not.toBeNull()
    expect(chip).toHaveClass('paused')
  })

  it('falls back to the raw status when no translation exists', () => {
    renderChip('mystery')
    expect(screen.getByText('mystery')).toBeInTheDocument()
  })

  it('translates labels for the selected language', async () => {
    await i18n.changeLanguage('de')
    renderChip('idle')
    // de.json maps status.idle → "Bereit"
    expect(screen.getByText('Bereit')).toBeInTheDocument()
  })
})
