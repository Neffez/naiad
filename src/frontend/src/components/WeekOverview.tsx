import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getUpcomingRuns, type ConfigDoc, type NextRun } from '../api/client'
import { queryKeys } from '../api/queryKeys'
import { resolveSeqColor } from '../theme/sequenceColors'

const WEEK_DAYS = 7

interface DayBucket {
  date: Date
  isToday: boolean
  runs: NextRun[]
}

function buildWeek(runs: NextRun[]): DayBucket[] {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const buckets: DayBucket[] = Array.from({ length: WEEK_DAYS }, (_, i) => {
    const date = new Date(today)
    date.setDate(today.getDate() + i)
    return { date, isToday: i === 0, runs: [] }
  })
  const byKey = new Map(buckets.map((b) => [b.date.toDateString(), b]))
  for (const run of runs) {
    byKey.get(new Date(run.scheduled_at).toDateString())?.runs.push(run)
  }
  return buckets
}

/** Calendar week view for the planner: the next 7 days with every upcoming run
 *  (recurring schedules and one-off plans merged, server-side). */
export function WeekOverview({ config }: { config: ConfigDoc | undefined }) {
  const { t, i18n } = useTranslation()
  const { data: runs = [] } = useQuery({
    queryKey: queryKeys.upcomingRuns(WEEK_DAYS),
    queryFn: () => getUpcomingRuns(WEEK_DAYS),
    refetchInterval: 60_000,
  })
  const week = buildWeek(runs)

  return (
    <section aria-label={t('planner.weekTitle')} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <span className="n-eyebrow">{t('planner.weekTitle')}</span>

      {/* Desktop: one column per day */}
      <div className="desktop-only">
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${WEEK_DAYS}, minmax(0, 1fr))`, gap: 8 }}>
          {week.map((day) => (
            <DayColumn key={day.date.toDateString()} day={day} config={config} lng={i18n.language} />
          ))}
        </div>
      </div>

      {/* Mobile: stacked list, days without runs collapsed to a single line */}
      <div className="mobile-only" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {week.map((day) => (
          <DayRow key={day.date.toDateString()} day={day} config={config} lng={i18n.language} />
        ))}
      </div>
    </section>
  )
}

function dayHeading(date: Date, lng: string): string {
  return date.toLocaleDateString(lng, { weekday: 'short', day: '2-digit', month: '2-digit' })
}

function RunEntry({ run, config, lng }: { run: NextRun; config: ConfigDoc | undefined; lng: string }) {
  const time = new Date(run.scheduled_at).toLocaleTimeString(lng, { hour: '2-digit', minute: '2-digit' })
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      <span aria-hidden="true" style={{
        flex: '0 0 3px', width: 3, height: 16, borderRadius: 2,
        background: resolveSeqColor(config, run.sequence_id) ?? 'var(--n-fg-dim)',
      }} />
      <span className="mono" style={{ fontSize: 11.5, color: 'var(--n-fg-soft)' }}>{time}</span>
      <span style={{
        fontSize: 11.5, minWidth: 0,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {run.sequence_label}
      </span>
    </div>
  )
}

function DayColumn({ day, config, lng }: { day: DayBucket; config: ConfigDoc | undefined; lng: string }) {
  const { t } = useTranslation()
  return (
    <div className="n-card" style={{
      padding: '10px 10px 12px',
      display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0,
      borderColor: day.isToday ? 'var(--n-glow-border)' : undefined,
    }}>
      <span className="n-eyebrow" style={{
        fontSize: 10.5,
        color: day.isToday ? 'var(--n-teal-200)' : undefined,
      }}>
        {dayHeading(day.date, lng)}
      </span>
      {day.runs.length === 0 ? (
        <span style={{ fontSize: 11.5, color: 'var(--n-fg-dim)' }}>{t('planner.weekNoRuns')}</span>
      ) : (
        day.runs.map((run, i) => (
          <RunEntry key={`${run.sequence_id}-${run.scheduled_at}-${i}`} run={run} config={config} lng={lng} />
        ))
      )}
    </div>
  )
}

function DayRow({ day, config, lng }: { day: DayBucket; config: ConfigDoc | undefined; lng: string }) {
  const { t } = useTranslation()
  return (
    <div className="n-card" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span className="n-eyebrow" style={{
        fontSize: 10.5,
        color: day.isToday ? 'var(--n-teal-200)' : undefined,
      }}>
        {dayHeading(day.date, lng)}
      </span>
      {day.runs.length === 0 ? (
        <span style={{ fontSize: 11.5, color: 'var(--n-fg-dim)' }}>{t('planner.weekNoRuns')}</span>
      ) : (
        day.runs.map((run, i) => (
          <RunEntry key={`${run.sequence_id}-${run.scheduled_at}-${i}`} run={run} config={config} lng={lng} />
        ))
      )}
    </div>
  )
}
