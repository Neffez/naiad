import { API_BASE } from './base'
import type { components, operations } from './schema'

/** API failure carrying the HTTP status (and Retry-After, when sent) so callers
 *  can branch on it — e.g. the login form telling a 429 lockout apart from a 401. */
export class ApiError extends Error {
  status: number
  /** Seconds from a Retry-After header, when the server sent one (429). */
  retryAfterS: number | null

  constructor(message: string, status: number, retryAfterS: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfterS = retryAfterS
  }
}

/** FastAPI's `detail` is a string for explicit HTTPExceptions but a list of
 *  objects for body-validation errors — stringify those instead of showing
 *  "[object Object]" in a toast. */
function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail) return detail
  if (detail != null && typeof detail === 'object') return JSON.stringify(detail)
  return fallback
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null)
  const retryAfter = Number(res.headers.get('Retry-After'))
  return new ApiError(
    detailMessage((body as { detail?: unknown } | null)?.detail, res.statusText),
    res.status,
    Number.isFinite(retryAfter) ? retryAfter : null,
  )
}

function getToken(): string | null {
  return localStorage.getItem('naiad_token')
}

export function setToken(token: string): void {
  localStorage.setItem('naiad_token', token)
}

export function clearToken(): void {
  localStorage.removeItem('naiad_token')
}

export function logout(): void {
  clearToken()
  window.dispatchEvent(new Event('naiad:unauthorized'))
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: { skipReloadOn401?: boolean },
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401 && !opts?.skipReloadOn401) {
    // Surface re-login via app state instead of a hard reload, so unsaved input
    // (Settings/Planner) isn't silently discarded. useAuth listens for this.
    clearToken()
    window.dispatchEvent(new Event('naiad:unauthorized'))
  }

  if (!res.ok) {
    throw await errorFromResponse(res)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}

type ApiSchemas = components['schemas']

async function authedFetch(path: string, init: RequestInit): Promise<Response> {
  const token = getToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('naiad:unauthorized'))
  }
  return res
}

// Auth
export const login = (password: string) =>
  api.post<LoginResponse>('/auth/login', { password })

export const verify = () =>
  request<VerifyTokenResponse>('GET', '/auth/verify', undefined, { skipReloadOn401: true })

// Sequences
export const getSequences = () => api.get<SequenceState[]>('/sequences')
export const startSequence = (id: string, duration_min?: number) =>
  api.post(`/sequences/${id}/start`, duration_min != null ? { duration_min } : undefined)
export const stopSequence = (id: string) => api.post(`/sequences/${id}/stop`)
export const pauseSequence = (id: string) => api.post(`/sequences/${id}/pause`)

// Single zones (run one zone in isolation, outside any sequence)
export const startZone = (id: string, duration_min: number) =>
  api.post(`/zones/${id}/start`, { duration_min })
export const stopZone = (id: string) => api.post(`/zones/${id}/stop`)

// System
export const getHealth = () => api.get<HealthInfo>('/health')

export const getStatus = () => api.get<SystemStatus>('/status')
export const setMaster = (on: boolean) => api.patch('/status/master', { on })
export const getValves = () => api.get<ValveState[]>('/valves')
export const skipRun = (body: SkipRunRequest) =>
  api.post('/status/skip-run', body)

// History
export const getHistory = (params: HistoryParams) => {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.per_page) qs.set('per_page', String(params.per_page))
  if (params.sequence_id) qs.set('sequence_id', params.sequence_id)
  if (params.zone_id) qs.set('zone_id', params.zone_id)
  if (params.from) qs.set('from', params.from)
  if (params.to) qs.set('to', params.to)
  return api.get<PaginatedHistory>(`/history?${qs}`)
}

// Aggregate over the last N local calendar days (today included), computed
// server-side so it is exact regardless of how many runs the window holds.
export const getHistorySummary = (days = 7) =>
  api.get<HistorySummary>(`/history/summary?days=${days}`)

// Decision log: why each automatic run (cron/plan/MQTT) started or was skipped.
export const getDecisions = (params: DecisionsParams) => {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.per_page) qs.set('per_page', String(params.per_page))
  if (params.sequence_id) qs.set('sequence_id', params.sequence_id)
  return api.get<PaginatedDecisions>(`/history/decisions?${qs}`)
}

// Deletes run history only — settings and plans are never affected.
// Pass olderThanDays to remove only entries older than that many days.
export const deleteHistory = (olderThanDays?: number) => {
  const qs = new URLSearchParams()
  if (olderThanDays != null) qs.set('older_than_days', String(olderThanDays))
  const suffix = qs.toString() ? `?${qs}` : ''
  return api.delete<DeleteHistoryResult>(`/history${suffix}`)
}

// Plans
export const getPlans = () => api.get<Plan[]>('/plans')
export const createPlan = (body: CreatePlanRequest) => api.post<Plan>('/plans', body)
export const deletePlan = (id: string) => api.delete(`/plans/${id}`)

// Settings
export const getSettings = () => api.get<AppSettings>('/settings')
export const updateSettings = (body: Partial<UpdateSettingsRequest>) =>
  api.patch<AppSettings>('/settings', body)
// Reset factor overrides back to the configured base values. Omit `group` to
// reset both the temperature and rain factors.
export const clearFactorOverrides = (group?: 'temp' | 'rain') =>
  api.delete<AppSettings>(`/settings/factors${group ? `?group=${group}` : ''}`)

// Configuration
export const getConfig = () => api.get<ConfigDoc>('/config')
export const putConfig = (body: ConfigUpdateRequest) => api.put<ConfigDoc>('/config', body)
export const getEntities = (domain?: string) =>
  api.get<EntitiesResponse>(`/config/entities${domain ? `?domain=${domain}` : ''}`)
export const getServices = (domain?: string) =>
  api.get<ServicesResponse>(`/config/services${domain ? `?domain=${domain}` : ''}`)
export const testNotify = (service?: string) =>
  api.post<TestNotifyResponse>(
    `/config/test-notify${service ? `?service=${encodeURIComponent(service)}` : ''}`,
  )

export async function exportConfig(): Promise<string> {
  const res = await authedFetch('/config/export', { method: 'GET' })
  if (!res.ok) throw new Error(res.statusText)
  return res.text()
}

export async function importConfig(text: string): Promise<ConfigDoc> {
  const res = await authedFetch('/config/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-yaml' },
    body: text,
  })
  if (!res.ok) {
    throw await errorFromResponse(res)
  }
  return res.json() as Promise<ConfigDoc>
}

// Preferences
export const getPreferences = () => api.get<UserPreferences>('/preferences')
export const updatePreferences = (body: UpdatePreferencesRequest) =>
  api.patch<UserPreferences>('/preferences', body)

// ── Types ─────────────────────────────────────────────────────────────────────

export type LoginResponse = ApiSchemas['LoginResponse']
export type VerifyTokenResponse =
  operations['verifyToken']['responses'][200]['content']['application/json']
export type HealthInfo =
  operations['getHealth']['responses'][200]['content']['application/json']
export type SkipRunRequest =
  operations['skipRun']['requestBody']['content']['application/json']

export type ZoneSummary = ApiSchemas['ZoneSummary']
export type FactorNotes = ApiSchemas['FactorNotes']
export type ScheduleSummary = ApiSchemas['ScheduleSummary']
export type SequenceState = ApiSchemas['SequenceState']
export type SystemStatus = ApiSchemas['SystemStatus']
export type NextRun = ApiSchemas['NextRunSummary']
export type ValveState = ApiSchemas['ValveState']
export type HistoryEntry = ApiSchemas['HistoryEntry']
export type PaginatedHistory = ApiSchemas['PaginatedHistory']

export interface HistoryParams {
  page?: number
  per_page?: number
  sequence_id?: string
  zone_id?: string
  from?: string
  to?: string
}

export type DecisionEntry = ApiSchemas['DecisionEntry']
export type PaginatedDecisions = ApiSchemas['PaginatedDecisions']

export interface DecisionsParams {
  page?: number
  per_page?: number
  sequence_id?: string
}

export type DeleteHistoryResult = ApiSchemas['DeleteHistoryResult']
export type HistorySummary = ApiSchemas['HistorySummary']
export type Plan = ApiSchemas['Plan']
export type CreatePlanRequest = ApiSchemas['CreatePlanRequest']
export type AppSettings = ApiSchemas['AppSettings']
export type UpdateSettingsRequest = ApiSchemas['UpdateSettingsRequest']
export type UserPreferences = ApiSchemas['UserPreferences']
export type UpdatePreferencesRequest = ApiSchemas['UpdatePreferencesRequest']

// ── Configuration ───────────────────────────────────────────────────────────

export const NOTIFICATION_CATEGORIES = ['start', 'skip', 'abort', 'reminder'] as const
export type NotificationCategory = ApiSchemas['NotificationCategory']
export type NotifyTarget = ApiSchemas['NotifyTarget']
export type HAConfigPublic = ApiSchemas['HAConfigPublic']
export type MQTTConfig = ApiSchemas['MQTTConfig']
export type AuthConfigResponse = ApiSchemas['AuthConfig']
export type SensorsConfig = ApiSchemas['SensorsConfig']
export type ZoneConfig = ApiSchemas['ZoneConfig']
export type SequenceColorKey = ApiSchemas['SequenceColorKey']
export type SequenceConfig = ApiSchemas['SequenceConfig']
export type FactorsConfig = ApiSchemas['FactorsConfig']
export type NotificationsConfig = ApiSchemas['NotificationsConfig']
export type ConfigDoc = ApiSchemas['ConfigDoc']
export type ConfigUpdateRequest = ApiSchemas['ConfigUpdateRequest']
export type EntityInfo = ApiSchemas['EntityInfo']
export type EntitiesResponse = ApiSchemas['EntitiesResponse']
export type ServicesResponse = ApiSchemas['ServicesResponse']
export type TestNotifyResponse = ApiSchemas['TestNotifyResponse']
