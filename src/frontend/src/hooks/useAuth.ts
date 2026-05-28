import { useCallback, useEffect, useState } from 'react'
import { clearToken, login as apiLogin, setToken, verify } from '../api/client'

export function useAuth() {
  const [authed, setAuthed] = useState<boolean | null>(null) // null = checking

  useEffect(() => {
    const token = localStorage.getItem('naiad_token')
    if (!token) { setAuthed(false); return }
    verify()
      .then(() => setAuthed(true))
      .catch(() => { clearToken(); setAuthed(false) })
  }, [])

  const login = useCallback(async (password: string) => {
    const res = await apiLogin(password)
    setToken(res.token)
    setAuthed(true)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setAuthed(false)
  }, [])

  return { authed, login, logout }
}
