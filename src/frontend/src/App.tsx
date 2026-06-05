import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from './api/queryKeys'
import { type ReactNode, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { IChart, IHome, ICal, ISettings } from './components/icons'
import { MasterToggle } from './components/MasterToggle'
import { Sidebar } from './components/Sidebar'
import { Toaster } from './components/Toast'
import { WeatherStrip } from './components/WeatherStrip'
import './i18n'
import './index.css'
import { useAuth } from './hooks/useAuth'
import { BASE_PATH } from './api/base'
import { getStatus, setMaster, type SystemStatus } from './api/client'
import Dashboard from './pages/Dashboard'
import History from './pages/History'
import Login from './pages/Login'
import Planner from './pages/Planner'
import SettingsLayout from './pages/settings/SettingsLayout'
import AdvancedSection from './pages/settings/sections/AdvancedSection'
import ConnectionSection from './pages/settings/sections/ConnectionSection'
import IntegrationsSection from './pages/settings/sections/IntegrationsSection'
import NotificationsSection from './pages/settings/sections/NotificationsSection'
import SequencesSection from './pages/settings/sections/SequencesSection'
import SystemSection from './pages/settings/sections/SystemSection'
import WateringSection from './pages/settings/sections/WateringSection'
import ZonesSection from './pages/settings/sections/ZonesSection'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000 } } })

function BottomNav() {
  const { t } = useTranslation()
  const items: { to: string; label: string; icon: ReactNode; end?: boolean }[] = [
    { to: '/', label: t('nav.dashboard'), icon: <IHome size={20} />, end: true },
    { to: '/planner', label: t('nav.planner'), icon: <ICal size={20} /> },
    { to: '/history', label: t('nav.history'), icon: <IChart size={20} /> },
    { to: '/settings', label: t('nav.settings'), icon: <ISettings size={20} /> },
  ]
  return (
    <nav
      aria-label={t('a11y.primaryNav')}
      style={{
        display: 'flex',
        justifyContent: 'space-around',
        alignItems: 'center',
        borderTop: '1px solid var(--n-line)',
        background: 'var(--n-bg-elev)',
        height: 64,
        padding: '0 4px',
        flexShrink: 0,
      }}
    >
      {items.map(({ to, label, icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          style={{ textDecoration: 'none', flex: 1 }}
        >
          {({ isActive }) => (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 2,
                padding: '6px 0',
                color: isActive ? 'var(--n-teal-200)' : 'var(--n-fg-muted)',
                fontSize: 10.5,
                letterSpacing: '0.02em',
              }}
            >
              {icon}
              <span>{label}</span>
            </div>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

function AppShell() {
  const { authed, login } = useAuth()
  const { t } = useTranslation()

  useEffect(() => {
    const theme = localStorage.getItem('naiad_theme') ?? 'dark'
    document.documentElement.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark')
  }, [])

  if (authed === null) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            border: '2px solid var(--n-teal-600)',
            borderTopColor: 'var(--n-teal-300)',
            animation: 'n-spin 0.8s linear infinite',
          }}
        />
      </div>
    )
  }

  if (!authed) return <Login onLogin={login} />

  return (
    <Router basename={BASE_PATH || undefined}>
      {/* Bounded to the viewport so the content area scrolls internally and the
          mobile bottom nav stays pinned (sticky) instead of scrolling off. */}
      <div style={{ height: '100dvh', display: 'flex', overflow: 'hidden' }}>
        {/* Skip link — first focusable element, lets keyboard users jump past the nav. */}
        <a href="#main-content" className="n-skip-link">{t('a11y.skipToContent')}</a>

        {/* Sidebar — visible on desktop (≥1024px), hidden on mobile */}
        <div className="desktop-only">
          <Sidebar />
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div id="main-content" tabIndex={-1} style={{ flex: 1, overflowY: 'auto', outline: 'none' }}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/planner" element={<PageShell title={t('nav.planner')}><Planner /></PageShell>} />
              <Route path="/history" element={<PageShell title={t('nav.history')}><History /></PageShell>} />
              <Route path="/settings" element={<PageShell title={t('nav.settings')}><SettingsLayout /></PageShell>}>
                <Route index element={<Navigate to="zones" replace />} />
                <Route path="zones" element={<ZonesSection />} />
                <Route path="sequences" element={<SequencesSection />} />
                <Route path="watering" element={<WateringSection />} />
                <Route path="notifications" element={<NotificationsSection />} />
                <Route path="connection" element={<ConnectionSection />} />
                <Route path="integrations" element={<IntegrationsSection />} />
                <Route path="advanced" element={<AdvancedSection />} />
                <Route path="system" element={<SystemSection />} />
              </Route>
              {/* Backward-compat: the standalone config page is now a settings section. */}
              <Route path="/config" element={<Navigate to="/settings" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>

          {/* Bottom nav — visible on mobile (<1024px), hidden on desktop */}
          <div className="mobile-only">
            <BottomNav />
          </div>
        </div>
      </div>
    </Router>
  )
}

function PageShell({ title, children }: { title: string; children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const { data: status } = useQuery<SystemStatus>({ queryKey: queryKeys.status, queryFn: getStatus, refetchInterval: 30_000 })
  const masterMut = useMutation({ mutationFn: (on: boolean) => setMaster(on), onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.status }) })
  const masterOn = status?.master_on ?? true

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      {/* Desktop header */}
      <header
        className="n-wavebed desktop-only"
        style={{
          height: 88, padding: '0 36px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: '1px solid var(--n-line)',
          flex: '0 0 88px', gap: 24, position: 'relative',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, minWidth: 0 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="n-eyebrow">Naiad</span>
            <span style={{ fontSize: 22, fontWeight: 500, letterSpacing: '-0.01em' }}>{title}</span>
          </div>
          <div className="n-vdivider" style={{ height: 40 }} />
          {status && <WeatherStrip sys={status} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div className="n-vdivider" style={{ height: 40 }} />
          <MasterToggle on={masterOn} onToggle={() => masterMut.mutate(!masterOn)} />
        </div>
      </header>

      {/* Mobile header */}
      <div className="mobile-only" style={{
        padding: '18px 20px 14px', display: 'flex', flexDirection: 'column', gap: 4,
        borderBottom: '1px solid var(--n-line)',
      }}>
        <span className="n-eyebrow">Naiad</span>
        <span style={{ fontSize: 20, fontWeight: 500 }}>{title}</span>
      </div>

      {/* Content */}
      <main style={{
        flex: 1, padding: '28px 44px 36px',
        overflowY: 'auto', scrollbarWidth: 'none',
      }}
        className="page-content"
      >
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AppShell />
      <Toaster />
    </QueryClientProvider>
  )
}
