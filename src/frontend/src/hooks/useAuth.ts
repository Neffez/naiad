import { useCallback, useEffect, useState } from 'react'
import { clearToken, login as apiLogin, setToken, verify } from '../api/client'

export function useAuth() {
  const [authed, setAuthed] = useState<boolean | null>(null) // null = checking

  useEffect(() => {
    verify()
      .then(() => setAuthed(true))
      .catch(() => {
        clearToken()
        setAuthed(false)
      })
  }, [])

  // A 401 from any request — or an explicit logout — dispatches this event.
  useEffect(() => {
    const onUnauthorized = () => setAuthed(false)
    window.addEventListener('naiad:unauthorized', onUnauthorized)
    return () => window.removeEventListener('naiad:unauthorized', onUnauthorized)
  }, [])

  const login = useCallback(async (password: string) => {
    const res = await apiLogin(password)
    setToken(res.token)
    setAuthed(true)
  }, [])

  return { authed, login }
}
