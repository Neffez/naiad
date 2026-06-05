import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'
import {
  GROUP_ORDER,
  SECTIONS,
  type SectionGroup,
  type SectionId,
} from '../../pages/settings/sectionsMeta'

// Section navigation for the settings area. Renders as a vertical grouped list
// on desktop and collapses to a horizontal scrollable pill rail on mobile
// (styling driven by .n-subnav* classes in index.css).
export function SubNav({ dirtySections, counts }: {
  dirtySections: Set<SectionId>
  counts: Partial<Record<SectionId, number>>
}) {
  const { t } = useTranslation()

  return (
    <nav className="n-subnav" aria-label={t('settings.title')}>
      {GROUP_ORDER.map((group: SectionGroup) => (
        <div className="n-subnav-group" key={group}>
          <span className="n-subnav-grouplabel">{t(`settings.group.${group}`)}</span>
          {SECTIONS.filter((s) => s.group === group).map((s) => {
            const count = counts[s.id]
            return (
              <NavLink
                key={s.id}
                to={s.id}
                className={({ isActive }) => `n-subnav-item${isActive ? ' active' : ''}`}
              >
                <span className="n-subnav-label">{t(`settings.nav.${s.id}`)}</span>
                {typeof count === 'number' && (
                  <span className="n-subnav-count">{count}</span>
                )}
                {dirtySections.has(s.id) && (
                  <span className="n-subnav-dot" aria-label={t('config.unsaved')} title={t('config.unsaved')} />
                )}
              </NavLink>
            )
          })}
        </div>
      ))}
    </nav>
  )
}
