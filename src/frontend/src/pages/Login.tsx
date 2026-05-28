import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
  onLogin: (password: string) => Promise<void>
}

export default function Login({ onLogin }: Props) {
  const { t } = useTranslation()
  const [pw, setPw] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await onLogin(pw)
    } catch {
      setError(t('login.error'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--n-bg)',
    }}>
      <div className="n-card" style={{ width: 320, padding: '32px 28px', display: 'flex', flexDirection: 'column', gap: 24 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>🌊</div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-teal-300)', letterSpacing: '-0.3px' }}>
            Naiad
          </h1>
          <p style={{ fontSize: 12, color: 'var(--n-text-3)', marginTop: 4 }}>
            Gartenbewässerung
          </p>
        </div>

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <input
            type="password"
            value={pw}
            onChange={e => setPw(e.target.value)}
            placeholder={t('login.password')}
            className="n-input"
            style={{ textAlign: 'center', letterSpacing: '0.2em' }}
            autoFocus
          />
          {error && (
            <p style={{ fontSize: 12, color: 'var(--n-danger)', textAlign: 'center' }}>{error}</p>
          )}
          <button
            type="submit"
            className="n-btn n-btn-primary"
            disabled={loading}
            style={{ width: '100%', justifyContent: 'center', padding: '10px' }}
          >
            {loading ? '…' : t('login.login')}
          </button>
        </form>
      </div>
    </div>
  )
}
