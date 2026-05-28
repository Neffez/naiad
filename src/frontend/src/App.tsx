import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import './i18n'
import './index.css'
import { useAuth } from './hooks/useAuth'
import Dashboard from './pages/Dashboard'
import History from './pages/History'
import Login from './pages/Login'
import Planner from './pages/Planner'
import Settings from './pages/Settings'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000 } } })

function BottomNav() {
  const { t } = useTranslation()
  const items = [
    { to: '/', label: t('nav.dashboard'), icon: '◉', end: true },
    { to: '/planner', label: t('nav.planner'), icon: '📅' },
    { to: '/history', label: t('nav.history'), icon: '📊' },
    { to: '/settings', label: t('nav.settings'), icon: '⚙' },
  ]
  return (
    <nav style={{
      display: 'flex',
      borderTop: '1px solid var(--n-border)',
      background: 'var(--n-surface)',
      position: 'sticky',
      bottom: 0,
    }}>
      {items.map(({ to, label, icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          style={({ isActive }) => ({
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: '10px 4px',
            fontSize: 10,
            fontWeight: 600,
            textDecoration: 'none',
            color: isActive ? 'var(--n-teal-300)' : 'var(--n-text-3)',
            gap: 3,
            transition: 'color 0.15s',
          })}
        >
          <span style={{ fontSize: 18 }}>{icon}</span>
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

function AppShell() {
  const { authed, login } = useAuth()

  useEffect(() => {
    const theme = localStorage.getItem('naiad_theme') ?? 'dark'
    document.documentElement.className = theme === 'light' ? 'theme-light' : ''
  }, [])

  if (authed === null) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 24, height: 24, borderRadius: '50%', border: '2px solid var(--n-teal-600)', borderTopColor: 'var(--n-teal-300)', animation: 'spin 0.8s linear infinite' }} />
      </div>
    )
  }

  if (!authed) return <Login onLogin={login} />

  return (
    <Router>
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/planner" element={<PageShell title=""><Planner /></PageShell>} />
            <Route path="/history" element={<PageShell title=""><History /></PageShell>} />
            <Route path="/settings" element={<PageShell title=""><Settings /></PageShell>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
        <BottomNav />
      </div>
    </Router>
  )
}

function PageShell({ children }: { children: React.ReactNode; title: string }) {
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', width: '100%', padding: '0 0 80px' }}>
      {children}
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AppShell />
    </QueryClientProvider>
  )
}
