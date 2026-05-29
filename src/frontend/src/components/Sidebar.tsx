import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'
import { IChart, ICal, IHome, ILogo, IMoon, ISettings } from './icons'

export function Sidebar() {
  const { t } = useTranslation()

  const items = [
    { to: '/', icon: <IHome size={22} />, label: t('nav.dashboard'), end: true },
    { to: '/planner', icon: <ICal size={22} />, label: t('nav.planner') },
    { to: '/history', icon: <IChart size={22} />, label: t('nav.history') },
    { to: '/settings', icon: <ISettings size={22} />, label: t('nav.settings') },
  ]

  function toggleTheme() {
    const current = localStorage.getItem('naiad_theme') ?? 'dark'
    const next = current === 'dark' ? 'light' : 'dark'
    localStorage.setItem('naiad_theme', next)
    document.documentElement.setAttribute('data-theme', next)
  }

  return (
    <div
      className="n-side"
      style={{
        width: 80,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '24px 0',
        gap: 8,
      }}
    >
      <div style={{ marginBottom: 12 }}>
        <ILogo size={30} />
      </div>
      {items.map(({ to, icon, label, end }) => (
        <NavLink key={to} to={to} end={end} style={{ textDecoration: 'none' }}>
          {({ isActive }) => (
            <button
              className={`n-iconbtn${isActive ? ' accent' : ''}`}
              style={{ width: 56, height: 56 }}
              title={label}
            >
              {icon}
            </button>
          )}
        </NavLink>
      ))}
      <div style={{ flex: 1 }} />
      <button className="n-iconbtn" style={{ width: 56, height: 56 }} title={t('nav.theme')} onClick={toggleTheme}>
        <IMoon size={20} />
      </button>
    </div>
  )
}
