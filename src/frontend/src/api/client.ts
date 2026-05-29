import { API_BASE } from './base'

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
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail?.detail ?? res.statusText)
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
  api.post<{ token: string; expires_at: string }>('/auth/login', { password })

export const verify = () =>
  request<{ valid: boolean }>('GET', '/auth/verify', undefined, { skipReloadOn401: true })

// Sequences
export const getSequences = () => api.get<SequenceState[]>('/sequences')
export const startSequence = (id: string, duration_min?: number) =>
  api.post(`/sequences/${id}/start`, duration_min != null ? { duration_min } : undefined)
export const stopSequence = (id: string) => api.post(`/sequences/${id}/stop`)
export const pauseSequence = (id: string) => api.post(`/sequences/${id}/pause`)

// System
export interface HealthInfo {
  status: string
  version: string
  ha_connected: boolean
}
export const getHealth = () => api.get<HealthInfo>('/health')

export const getStatus = () => api.get<SystemStatus>('/status')
export const setMaster = (on: boolean) => api.patch('/status/master', { on })
export const getValves = () => api.get<ValveState[]>('/valves')

// History
export const getHistory = (params: HistoryParams) => {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.per_page) qs.set('per_page', String(params.per_page))
  if (params.sequence_id) qs.set('sequence_id', params.sequence_id)
  if (params.from) qs.set('from', params.from)
  if (params.to) qs.set('to', params.to)
  return api.get<PaginatedHistory>(`/history?${qs}`)
}

// Plans
export const getPlans = () => api.get<Plan[]>('/plans')
export const createPlan = (body: CreatePlanRequest) => api.post<Plan>('/plans', body)
export const deletePlan = (id: string) => api.delete(`/plans/${id}`)

// Settings
export const getSettings = () => api.get<AppSettings>('/settings')
export const updateSettings = (body: Partial<UpdateSettingsRequest>) =>
  api.patch<AppSettings>('/settings', body)

// Configuration
export const getConfig = () => api.get<ConfigDoc>('/config')
export const putConfig = (body: ConfigDoc) => api.put<ConfigDoc>('/config', body)
export const getEntities = (domain?: string) =>
  api.get<{ entities: EntityInfo[] }>(`/config/entities${domain ? `?domain=${domain}` : ''}`)

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
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail?.detail ?? res.statusText)
  }
  return res.json() as Promise<ConfigDoc>
}

// Preferences
export const getPreferences = () => api.get<UserPreferences>('/preferences')
export const updatePreferences = (body: Partial<UserPreferences>) =>
  api.patch<UserPreferences>('/preferences', body)

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ZoneSummary {
  id: string
  label: string
  valve_state: 'on' | 'off' | 'unknown'
}

export interface SequenceState {
  id: string
  label: string
  status: 'running' | 'idle' | 'paused' | 'disabled'
  enabled: boolean
  paused: boolean
  factor_pct: number
  factor_note: string | null
  schedule_label: string
  next_run_at: string | null
  zones: ZoneSummary[]
  basis_min_per_zone: number
  current_run: null | { zone_id: string; elapsed_min: number; remaining_min: number }
}

export interface SystemStatus {
  master_on: boolean
  ha_connected: boolean
  weather: { temp_c: number | null; rain_24h_mm: number; wind_label: string; season_active: boolean }
  today_factor: { temp_pct: number; rain_pct: number; combined_pct: number; wind_blocking_sequences: string[] }
  next_run: NextRun | null
  after_next: NextRun | null
  liters_today: number
  liters_week: number
  week_series: number[]
}

export interface NextRun {
  sequence_id: string
  sequence_label: string
  scheduled_at: string
  duration_min: number
}

export interface ValveState {
  id: string
  zone_id: string
  label: string
  state: 'on' | 'off' | 'unknown'
  on_since: string | null
  runtime_min: number | null
}

export interface HistoryEntry {
  id: number
  zone_id: string
  zone_label: string
  sequence_id: string
  sequence_label: string
  started_at: string
  ended_at: string | null
  duration_min: number | null
  liters: number | null
  triggered_by: string
  aborted: boolean
  abort_reason: string | null
}

export interface PaginatedHistory {
  items: HistoryEntry[]
  total: number
  page: number
  per_page: number
}

export interface HistoryParams {
  page?: number
  per_page?: number
  sequence_id?: string
  from?: string
  to?: string
}

export interface Plan {
  id: string
  sequence_id: string
  sequence_label: string
  scheduled_at: string
  duration_min: number | null
  estimated_liters: number | null
  created_at: string
}

export interface CreatePlanRequest {
  sequence_id: string
  mode: 'in_hours' | 'at_datetime'
  value: number | string
  duration_min?: number
}

export interface AppSettings {
  sequences: Record<string, { basis_min_per_zone: number | null; watchdog_min: number | null; paused: boolean }>
  factors: {
    temp: { basis_c: number; pct_per_c: number; min_pct: number; max_pct: number }
    rain: { forecast_days: number; threshold_prob: number; reduce_above_mm: number; zero_above_mm: number; forecast_decay: number }
  }
  token_lifetime_days: number
  auto_login_enabled: boolean
}

export interface UpdateSettingsRequest {
  sequences?: Record<string, { basis_min_per_zone?: number; watchdog_min?: number; paused?: boolean }>
  factors?: {
    temp?: Partial<AppSettings['factors']['temp']>
    rain?: Partial<AppSettings['factors']['rain']>
  }
  token_lifetime_days?: number
  auto_login_enabled?: boolean
}

export interface UserPreferences {
  theme: 'dark' | 'light'
  language: 'de' | 'en'
}

// ── Configuration ───────────────────────────────────────────────────────────

export interface ZoneConfig {
  label: string
  switch: string
  flow_lph: number
}

export interface SequenceConfig {
  label: string
  zones: string[]
  basis_min_per_zone: number
  range: [number, number]
  watchdog_min: number
  schedule: { cron: string }
  enabled: boolean
  wind_blocks: boolean
}

export interface SensorsConfig {
  rain: string
  wind: string
  season: string
  temperature: string
  precipitation_prob_today: string
  precipitation_prob_tomorrow: string
  precipitation_today: string
  precipitation_tomorrow: string
}

export interface FactorsConfig {
  temp: { formula: 'linear'; basis_c: number; pct_per_c: number; min_pct: number; max_pct: number }
  rain: {
    forecast_days: number
    threshold_prob: number
    reduce_above_mm: number
    zero_above_mm: number
    forecast_decay: number
  }
}

export interface HAConfigPublic {
  url: string
  notify_targets: string[]
}

export interface AuthConfigResponse {
  mode: 'password' | 'forward_header' | 'none'
  forward_header: { header: string; trusted_proxies: string[] }
  auto_login: { enabled: boolean; trigger: { url_param: string; trusted_referers: string[]; trusted_ips: string[] } }
  frame_ancestors: string[]
  password_set: boolean
}

export interface ConfigDoc {
  ha: HAConfigPublic
  auth: AuthConfigResponse
  sensors: SensorsConfig
  zones: Record<string, ZoneConfig>
  sequences: Record<string, SequenceConfig>
  factors: FactorsConfig
  timezone: string
  restart_required: boolean
}

export interface EntityInfo {
  entity_id: string
  friendly_name: string | null
  state: string
  domain: string
}
