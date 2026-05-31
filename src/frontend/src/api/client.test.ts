import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setToken, clearToken, login, getSequences, getHealth } from './client'

const TOKEN_KEY = 'naiad_token'

// Build a minimal fetch Response stand-in.
function mockResponse(body: unknown, init: { status?: number } = {}): Response {
  const status = init.status ?? 200
  const ok = status >= 200 && status < 300
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Error',
    json: async () => body,
  } as unknown as Response
}

describe('token storage', () => {
  beforeEach(() => localStorage.clear())

  it('persists a token in localStorage', () => {
    setToken('abc123')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('abc123')
  })

  it('removes the token on clear', () => {
    setToken('abc123')
    clearToken()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })
})

describe('request layer', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('sends JSON content-type and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse([{ id: 's1' }]))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getSequences()

    expect(result).toEqual([{ id: 's1' }])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/sequences')
    expect((init as RequestInit).method).toBe('GET')
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/json')
    expect(headers['Authorization']).toBeUndefined()
  })

  it('attaches a bearer token when one is stored', async () => {
    setToken('secret')
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    await getHealth()

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer secret')
  })

  it('serialises the request body for POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ token: 't', expires_at: 'x' }))
    vi.stubGlobal('fetch', fetchMock)

    await login('hunter2')

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ password: 'hunter2' }))
  })

  it('clears the token and emits naiad:unauthorized on 401', async () => {
    setToken('expired')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse({ detail: 'nope' }, { status: 401 })))
    const onUnauthorized = vi.fn()
    window.addEventListener('naiad:unauthorized', onUnauthorized)

    await expect(getSequences()).rejects.toThrow('nope')

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    window.removeEventListener('naiad:unauthorized', onUnauthorized)
  })

  it('throws the server-provided detail message on error responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse({ detail: 'Sequence already running' }, { status: 409 })))
    await expect(getSequences()).rejects.toThrow('Sequence already running')
  })

  it('falls back to statusText when the error body has no detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => {
          throw new Error('not json')
        },
      } as unknown as Response),
    )
    await expect(getSequences()).rejects.toThrow('Internal Server Error')
  })

  it('returns undefined for a 204 No Content response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => {
        throw new Error('should not be called')
      },
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    await expect(getSequences()).resolves.toBeUndefined()
  })
})
