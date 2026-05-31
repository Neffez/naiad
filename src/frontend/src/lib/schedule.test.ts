import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import type { ScheduleSummary } from '../api/client'
import {
  isDaily,
  isWeekdays,
  isWeekend,
  weekdayShort,
  formatDays,
  formatSchedule,
  dailyCronToTime,
  timeToDailyCron,
} from './schedule'

// A minimal translation stub: returns a recognisable string per key so we can
// assert on structure without depending on the real locale files.
const labels: Record<string, string> = {
  'schedule.daily': 'Daily',
  'schedule.weekdays': 'Weekdays',
  'schedule.weekend': 'Weekend',
  'schedule.none': 'No schedule',
  'weekday.short.1': 'Mon',
  'weekday.short.2': 'Tue',
  'weekday.short.3': 'Wed',
  'weekday.short.6': 'Sat',
  'weekday.short.7': 'Sun',
}
const t = ((key: string) => labels[key] ?? key) as unknown as TFunction

function schedule(partial: Partial<ScheduleSummary>): ScheduleSummary {
  return { days: [], times: [], cron: null, ...partial }
}

describe('day-set helpers', () => {
  it('treats an empty day list as daily', () => {
    expect(isDaily([])).toBe(true)
    expect(isDaily([1])).toBe(false)
  })

  it('recognises the Mon–Fri weekday set regardless of order', () => {
    expect(isWeekdays([5, 4, 3, 2, 1])).toBe(true)
    expect(isWeekdays([1, 2, 3, 4])).toBe(false)
    expect(isWeekdays([1, 2, 3, 4, 5, 6])).toBe(false)
  })

  it('recognises the Sat–Sun weekend set', () => {
    expect(isWeekend([7, 6])).toBe(true)
    expect(isWeekend([6])).toBe(false)
  })
})

describe('weekdayShort', () => {
  it('looks up the localized short name', () => {
    expect(weekdayShort(1, t)).toBe('Mon')
    expect(weekdayShort(7, t)).toBe('Sun')
  })
})

describe('formatDays', () => {
  it('collapses recognised sets to a single label', () => {
    expect(formatDays([], t)).toBe('Daily')
    expect(formatDays([1, 2, 3, 4, 5], t)).toBe('Weekdays')
    expect(formatDays([6, 7], t)).toBe('Weekend')
  })

  it('lists individual days sorted and comma-separated', () => {
    expect(formatDays([3, 1, 2], t)).toBe('Mon, Tue, Wed')
  })
})

describe('formatSchedule', () => {
  it('returns the raw cron string when an advanced override is set', () => {
    expect(formatSchedule(schedule({ cron: '0 6 * * 1-5' }), t)).toBe('0 6 * * 1-5')
  })

  it('returns the empty-schedule label when there are no times', () => {
    expect(formatSchedule(schedule({ days: [1], times: [] }), t)).toBe('No schedule')
  })

  it('combines the day label with the times', () => {
    expect(formatSchedule(schedule({ days: [], times: ['06:00', '21:30'] }), t)).toBe(
      'Daily · 06:00, 21:30',
    )
  })
})

describe('daily cron round-trip', () => {
  it('parses a simple daily cron into HH:MM', () => {
    expect(dailyCronToTime('30 6 * * *')).toBe('06:30')
    expect(dailyCronToTime('0 21 * * *')).toBe('21:00')
  })

  it('rejects non-daily or malformed cron expressions', () => {
    expect(dailyCronToTime('30 6 * * 1-5')).toBeNull()
    expect(dailyCronToTime('30 6 1 * *')).toBeNull()
    expect(dailyCronToTime('70 6 * * *')).toBeNull()
    expect(dailyCronToTime('30 25 * * *')).toBeNull()
    expect(dailyCronToTime('not a cron')).toBeNull()
  })

  it('builds a daily cron from HH:MM and round-trips losslessly', () => {
    expect(timeToDailyCron('06:30')).toBe('30 6 * * *')
    expect(dailyCronToTime(timeToDailyCron('21:05'))).toBe('21:05')
  })
})
