import { useTranslation } from 'react-i18next'
import { Check, Num, Row, Section } from '../../../components/config/primitives'
import { inputStyle } from '../../../components/config/formStyles'
import { useConfig } from '../ConfigContext'

export default function IntegrationsSection() {
  const { t } = useTranslation()
  const { draft, patch } = useConfig()

  return (
    // MQTT statistics bridge — publishes tracked liters/durations to HA.
    <Section title={t('config.mqtt')}>
      <Row label={t('config.mqttEnabled')}>
        <Check
          label={t('config.mqttEnabledHint')}
          checked={draft.mqtt.enabled}
          onChange={(v) => patch((d) => { d.mqtt.enabled = v })}
        />
      </Row>
      <Row label={t('config.mqttHost')}>
        <input
          style={{ ...inputStyle, width: 280 }}
          value={draft.mqtt.host}
          placeholder="core-mosquitto"
          aria-label={t('config.mqttHost')}
          onChange={(e) => patch((d) => { d.mqtt.host = e.target.value })}
        />
      </Row>
      <Row label={t('config.mqttPort')}>
        <Num value={draft.mqtt.port} ariaLabel={t('config.mqttPort')} onChange={(v) => patch((d) => { d.mqtt.port = v })} />
      </Row>
      <Row label={t('config.mqttUsername')}>
        <input
          style={{ ...inputStyle, width: 200 }}
          value={draft.mqtt.username}
          aria-label={t('config.mqttUsername')}
          onChange={(e) => patch((d) => { d.mqtt.username = e.target.value })}
        />
      </Row>
      <Row label={t('config.mqttBaseTopic')} last>
        <input
          style={{ ...inputStyle, width: 200, fontFamily: 'var(--n-mono, monospace)' }}
          value={draft.mqtt.base_topic}
          aria-label={t('config.mqttBaseTopic')}
          onChange={(e) => patch((d) => { d.mqtt.base_topic = e.target.value })}
        />
      </Row>
    </Section>
  )
}
