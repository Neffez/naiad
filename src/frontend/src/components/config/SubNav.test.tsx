import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import i18n from '../../i18n'
import { SubNav } from './SubNav'
import { type SectionId } from '../../pages/settings/sectionsMeta'

// Render SubNav as the element of the /settings route so relative NavLink targets
// (to="zones" …) resolve exactly as they do in the real app.
function renderNav(dirty: SectionId[] = [], counts: Partial<Record<SectionId, number>> = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter initialEntries={['/settings/zones']}>
        <Routes>
          <Route
            path="/settings"
            element={<SubNav dirtySections={new Set(dirty)} counts={counts} />}
          >
            <Route path="zones" element={null} />
          </Route>
        </Routes>
      </MemoryRouter>
    </I18nextProvider>,
  )
}

describe('SubNav', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('renders every section as a link', () => {
    const { container } = renderNav()
    const labels = [...container.querySelectorAll('.n-subnav-label')].map((n) => n.textContent)
    expect(labels).toEqual(['Zones', 'Sequences', 'Watering', 'Notifications', 'Connection', 'Integrations', 'Advanced', 'System'])
  })

  it('renders the navigation group headers', () => {
    renderNav()
    expect(screen.getByText('Operation')).toBeInTheDocument()
    expect(screen.getByText('Setup')).toBeInTheDocument()
  })

  it('shows a count badge for sections that provide one', () => {
    const { container } = renderNav([], { zones: 3 })
    const counts = container.querySelectorAll('.n-subnav-count')
    expect(counts).toHaveLength(1)
    expect(counts[0]).toHaveTextContent('3')
  })

  it('shows a dirty dot only for dirty sections', () => {
    const { container } = renderNav(['sequences'])
    expect(container.querySelectorAll('.n-subnav-dot')).toHaveLength(1)
  })

  it('marks the active route link', () => {
    const { container } = renderNav()
    const active = container.querySelector('.n-subnav-item.active')
    expect(active).not.toBeNull()
    expect(active).toHaveTextContent('Zones')
  })
})
