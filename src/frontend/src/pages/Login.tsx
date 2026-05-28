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
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--n-bg)' }}>
      <div className="n-card p-8 w-80 flex flex-col gap-4">
        <h1 className="text-2xl font-semibold text-center" style={{ color: 'var(--n-teal-300)' }}>
          {t('login.title')}
        </h1>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <input
            type="password"
            value={pw}
            onChange={e => setPw(e.target.value)}
            placeholder={t('login.password')}
            className="rounded-lg px-3 py-2 outline-none"
            style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)' }}
            autoFocus
          />
          {error && <p className="text-sm" style={{ color: 'var(--n-danger)' }}>{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg py-2 font-medium transition-opacity"
            style={{ background: 'var(--n-teal-600)', color: '#fff', opacity: loading ? 0.6 : 1 }}
          >
            {t('login.login')}
          </button>
        </form>
      </div>
    </div>
  )
}
