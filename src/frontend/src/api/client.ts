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

// Single zones (run one zone in isolation, outside any sequence)
export const startZone = (id: string, duration_min: number) =>
  api.post(`/zones/${id}/start`, { duration_min })
export const stopZone = (id: string) => api.post(`/zones/${id}/stop`)

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
export const skipRun = (body: { sequence_id: string; scheduled_at: string; plan_id?: string | null }) =>
  api.post('/status/skip-run', body)

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

// Configuration
export const getConfig = () => api.get<ConfigDoc>('/config')
export const putConfig = (body: ConfigDoc) => api.put<ConfigDoc>('/config', body)
export const getEntities = (domain?: string) =>
  api.get<{ entities: EntityInfo[] }>(`/config/entities${domain ? `?domain=${domain}` : ''}`)
export const getServices = (domain?: string) =>
  api.get<{ services: string[] }>(`/config/services${domain ? `?domain=${domain}` : ''}`)
export const testNotify = (service?: string) =>
  api.post<{ sent: number; targets: string[] }>(
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

export interface FactorNotes {
  season_off: boolean
  wind_blocked: boolean
  rain_factor_pct: number | null
  temp_delta_pct: number | null
}

export interface ScheduleSummary {
  days: number[] // ISO weekdays 1=Mon … 7=Sun; empty = every day
  times: string[] // "HH:MM"
  cron: string | null // advanced override; set only when active
}

export interface SequenceState {
  id: string
  label: string
  status: 'running' | 'idle' | 'paused' | 'disabled'
  enabled: boolean
  paused: boolean
  factor_pct: number
  factor_notes: FactorNotes
  schedule: ScheduleSummary
  next_run_at: string | null
  zones: ZoneSummary[]
  basis_min_per_zone: number
  current_run: null | { zone_id: string; elapsed_min: number; remaining_min: number }
}

export interface SystemStatus {
  master_on: boolean
  ha_connected: boolean
  weather: { temp_c: number | null; rain_24h_mm: number; wind_label: string; season_active: boolean }
  // temp_pct and rain_pct are signed deltas from neutral (0 = no adjustment); combined_pct is the overall factor (100 = neutral).
  today_factor: {
    temp_pct: number; rain_pct: number; combined_pct: number; manual: boolean; wind_blocking_sequences: string[]
    temp_input_c: number | null; rain_prob_pct: number | null; rain_mm: number | null
  }
  next_run: NextRun | null
  after_next: NextRun | null
  upcoming_runs: NextRun[]
  liters_today: number
  liters_week: number
  week_series: number[]
}

export interface NextRun {
  sequence_id: string
  sequence_label: string
  scheduled_at: string
  duration_min: number
  plan_id?: string | null
  /** True when this is the run currently executing (live, not skippable). */
  in_progress?: boolean
}

export interface ValveState {
  id: string
  zone_id: string
  label: string
  state: 'on' | 'off' | 'unknown'
  on_since: string | null
  runtime_min: number | null
  /** Planned total duration of a single-zone run, for remaining-time display. */
  total_min?: number | null
  /** True when this zone is running as a standalone single-zone run (stoppable directly). */
  single_run: boolean
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

export interface DeleteHistoryResult {
  deleted: number
}

export interface Plan {
  id: string
  target_type: 'sequence' | 'zone'
  sequence_id: string | null
  sequence_label: string | null
  zone_id: string | null
  zone_label: string | null
  /** Unified display label (sequence or zone). */
  label: string
  scheduled_at: string
  duration_min: number | null
  estimated_liters: number | null
  created_at: string
}

export interface CreatePlanRequest {
  // Exactly one of sequence_id / zone_id. A zone plan requires duration_min.
  sequence_id?: string
  zone_id?: string
  mode: 'in_hours' | 'at_datetime'
  value: number | string
  duration_min?: number
}

export interface AppSettings {
  sequences: Record<string, { basis_min_per_zone: number | null; watchdog_min: number | null; paused: boolean }>
  factors: {
    temp: { basis_c: number; pct_per_c: number; min_pct: number; max_pct: number }
    rain: { forecast_days: number; threshold_prob: number; reduce_above_mm: number; zero_above_mm: number; forecast_decay: number }
    manual_mode: boolean
    manual_pct: number | null
  }
  token_lifetime_days: number
  auto_login_enabled: boolean
}

export interface UpdateSettingsRequest {
  sequences?: Record<string, { basis_min_per_zone?: number; watchdog_min?: number; paused?: boolean }>
  factors?: {
    temp?: Partial<AppSettings['factors']['temp']>
    rain?: Partial<AppSettings['factors']['rain']>
    manual_mode?: boolean
    manual_pct?: number
  }
  token_lifetime_days?: number
  auto_login_enabled?: boolean
}

export interface UserPreferences {
  theme: 'dark' | 'light'
  language: 'de' | 'en'
  /** Sequence IDs in the user's preferred dashboard order. IDs not listed are appended. */
  sequence_order: string[]
  /** Zone (valve) IDs in the user's preferred dashboard order. IDs not listed are appended. */
  zone_order: string[]
}

// ── Configuration ───────────────────────────────────────────────────────────

export interface ZoneConfig {
  label: string
  switch: string
  flow_lph: number
}

export type SequenceColorKey = 'green' | 'sand' | 'purple' | 'slate' | 'blue' | 'rose'

export interface SequenceConfig {
  label: string
  zones: string[]
  basis_min_per_zone: number
  range: [number, number]
  watchdog_min: number
  schedule: ScheduleSummary
  enabled: boolean
  wind_blocks: boolean
  color: SequenceColorKey | null
}

export interface SensorsConfig {
  rain: string
  wind: string
  season: string
  temperature: string
  temperature_max: string
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

export const NOTIFICATION_CATEGORIES = ['start', 'skip', 'abort', 'reminder'] as const
export type NotificationCategory = (typeof NOTIFICATION_CATEGORIES)[number]

export interface NotifyTarget {
  service: string
  categories: NotificationCategory[]
  quiet: boolean
  platform: 'auto' | 'ios' | 'android'
}

export interface HAConfigPublic {
  url: string
  notify_targets: NotifyTarget[]
}

export interface MQTTConfig {
  enabled: boolean
  host: string
  port: number
  username: string
  client_id: string
  discovery_prefix: string
  base_topic: string
  // Present in the GET response only — the password itself is never exposed and
  // is environment-managed (MQTT_PASSWORD). Echoed back on save; the server drops it.
  password_set?: boolean
}

export interface AuthConfigResponse {
  mode: 'password' | 'forward_header' | 'none'
  forward_header: { header: string; trusted_proxies: string[] }
  auto_login: { enabled: boolean; trigger: { url_param: string; trusted_referers: string[]; trusted_ips: string[] } }
  frame_ancestors: string[]
  password_set: boolean
}

export interface NotificationsConfig {
  evening_reminder_cron: string
}

export interface ConfigDoc {
  ha: HAConfigPublic
  mqtt: MQTTConfig
  auth: AuthConfigResponse
  sensors: SensorsConfig
  zones: Record<string, ZoneConfig>
  sequences: Record<string, SequenceConfig>
  factors: FactorsConfig
  notifications: NotificationsConfig
  timezone: string
  sequence_colors_enabled: boolean
  restart_required: boolean
}

export interface EntityInfo {
  entity_id: string
  friendly_name: string | null
  state: string
  domain: string
}
