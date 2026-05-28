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

function Nav() {
  const { t } = useTranslation()
  const linkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
    color: isActive ? 'var(--n-teal-300)' : 'var(--n-text-dim)',
    fontWeight: isActive ? 600 : 400,
    textDecoration: 'none',
    fontSize: 14,
    padding: '10px 14px',
    display: 'inline-block',
  })

  return (
    <nav style={{ background: 'var(--n-card)', borderBottom: '1px solid var(--n-border)' }}>
      <div style={{ display: 'flex', gap: 4, padding: '0 8px', maxWidth: 1200, margin: '0 auto' }}>
        <NavLink to="/" end style={linkStyle}>{t('nav.dashboard')}</NavLink>
        <NavLink to="/planner" style={linkStyle}>{t('nav.planner')}</NavLink>
        <NavLink to="/history" style={linkStyle}>{t('nav.history')}</NavLink>
        <NavLink to="/settings" style={linkStyle}>{t('nav.settings')}</NavLink>
      </div>
    </nav>
  )
}

function AppShell() {
  const { authed, login } = useAuth()

  useEffect(() => {
    const theme = localStorage.getItem('naiad_theme') ?? 'dark'
    document.documentElement.className = theme === 'light' ? 'light' : ''
  }, [])

  if (authed === null) return null

  if (!authed) return <Login onLogin={login} />

  return (
    <Router>
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <Nav />
        <main style={{ flex: 1, maxWidth: 1200, margin: '0 auto', width: '100%' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/planner" element={<Planner />} />
            <Route path="/history" element={<History />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AppShell />
    </QueryClientProvider>
  )
}
