import { useTranslation } from 'react-i18next'
import { testNotify } from '../../../api/client'
import { InfoTip } from '../../../components/InfoTip'
import { toast } from '../../../components/Toast'
import { NotifyTargetList, ReminderTime } from '../../../components/config/editors'
import { Row, Section } from '../../../components/config/primitives'
import { inputStyle } from '../../../components/config/formStyles'
import { useConfig } from '../ConfigContext'

export default function NotificationsSection() {
  const { t } = useTranslation()
  const { draft, patch, dirty, notifyServices } = useConfig()

  async function handleTestNotify() {
    try {
      const r = await testNotify()
      toast(t('config.notifyTestOk', { count: r.sent }), 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    // Notifications (global) — per-recipient choices live on each notify target below.
    <Section title={t('config.notifications')}>
      <Row label={t('config.notifyReminderTime')}>
        <ReminderTime
          value={draft.notifications.evening_reminder_cron}
          onChange={(cron) => patch((d) => { d.notifications.evening_reminder_cron = cron })}
        />
      </Row>
      <Row
        label={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            {t('config.notifyQueueMaxHours')}
            <InfoTip text={t('config.notifyQueueMaxHoursHelp')} />
          </span>
        }
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="number" min={0} step={1}
            aria-label={t('config.notifyQueueMaxHours')}
            style={{ ...inputStyle, width: 120, fontVariantNumeric: 'tabular-nums' }}
            value={draft.notifications.queue_max_hours}
            onChange={(e) => patch((d) => {
              const n = Number(e.target.value)
              d.notifications.queue_max_hours = e.target.value === '' || Number.isNaN(n) ? 0 : Math.max(0, n)
            })}
          />
          <span style={{ color: 'var(--n-dim)', fontSize: 13 }}>{t('config.notifyQueueMaxHoursUnit')}</span>
        </div>
      </Row>
      <Row label={t('config.notifyTargets')} last align="start">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
          <NotifyTargetList
            values={draft.ha.notify_targets}
            services={notifyServices}
            dirty={dirty}
            onChange={(vals) => patch((d) => { d.ha.notify_targets = vals })}
          />
          <button
            className="n-btn"
            style={{ height: 32, padding: '0 12px', fontSize: 12.5, alignSelf: 'flex-start' }}
            disabled={dirty || draft.ha.notify_targets.length === 0}
            title={dirty ? t('config.saveFirst') : undefined}
            onClick={handleTestNotify}
          >
            {t('config.notifyTest')}
          </button>
        </div>
      </Row>
    </Section>
  )
}
