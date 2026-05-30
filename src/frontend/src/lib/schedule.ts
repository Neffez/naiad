import type { TFunction } from 'i18next'
import type { ScheduleSummary } from '../api/client'

// ── Constants ─────────────────────────────────────────────────────────────────

// ISO weekday order Mon…Sun (1…7). The picker and the stored schedule use this.
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const
export const MAX_TIMES = 5

const WEEKDAYS_SET = [1, 2, 3, 4, 5]
const WEEKEND_SET = [6, 7]

const sameSet = (a: number[], b: number[]): boolean =>
  a.length === b.length && [...a].sort().join() === [...b].sort().join()

/** Localized short weekday name for an ISO weekday (1=Mon … 7=Sun). */
export function weekdayShort(iso: number, t: TFunction): string {
  return t(`weekday.short.${iso}`)
}

// ── Day-set helpers ───────────────────────────────────────────────────────────

export const isDaily = (days: number[]): boolean => days.length === 0
export const isWeekdays = (days: number[]): boolean => sameSet(days, WEEKDAYS_SET)
export const isWeekend = (days: number[]): boolean => sameSet(days, WEEKEND_SET)

/** A compact, localized description of the selected days. */
export function formatDays(days: number[], t: TFunction): string {
  if (isDaily(days)) return t('schedule.daily')
  if (isWeekdays(days)) return t('schedule.weekdays')
  if (isWeekend(days)) return t('schedule.weekend')
  return [...days]
    .sort((a, b) => a - b)
    .map((d) => weekdayShort(d, t))
    .join(', ')
}

/**
 * Human-readable summary of a schedule, e.g. "Mo–Fr · 06:00, 21:30".
 * Falls back to the raw cron string when an advanced override is active.
 */
export function formatSchedule(schedule: ScheduleSummary, t: TFunction): string {
  if (schedule.cron) return schedule.cron
  if (schedule.times.length === 0) return t('schedule.none')
  return `${formatDays(schedule.days, t)} · ${schedule.times.join(', ')}`
}

// ── Daily-time cron round-trip (used for the evening reminder) ─────────────────

/** Parse a daily cron ("M H * * *") into "HH:MM", or null if not a simple daily time. */
export function dailyCronToTime(cron: string): string | null {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return null
  const [minute, hour, dom, month, dow] = parts
  if (dom !== '*' || month !== '*' || dow !== '*') return null
  if (!/^\d{1,2}$/.test(minute) || !/^\d{1,2}$/.test(hour)) return null
  const m = Number(minute)
  const h = Number(hour)
  if (m > 59 || h > 23) return null
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** Build a daily cron ("M H * * *") from an "HH:MM" string. */
export function timeToDailyCron(time: string): string {
  const [h, m] = time.split(':')
  return `${Number(m)} ${Number(h)} * * *`
}
