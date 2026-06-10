import { useTranslation } from 'react-i18next'
import { type ConfigDoc } from '../../../api/client'
import { InfoTip } from '../../../components/InfoTip'
import { NumberField } from '../../../components/NumberField'
import { EntityCombobox, Row, Section } from '../../../components/config/primitives'
import { inputStyle } from '../../../components/config/formStyles'
import { useConfig } from '../ConfigContext'

export default function ConnectionSection() {
  const { t } = useTranslation()
  const { draft, patch, entitiesByDomain } = useConfig()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <Section title={t('config.ha')}>
        <Row label={t('config.haUrl')} last>
          <input
            style={{ ...inputStyle, width: 360 }}
            value={draft.ha.url}
            aria-label={t('config.haUrl')}
            onChange={(e) => patch((d) => { d.ha.url = e.target.value })}
          />
        </Row>
      </Section>

      <Section title={t('config.sensors')}>
        {SENSOR_FIELDS.map((f, i) => (
          <Row
            key={f.key}
            label={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                {t(`config.sensor.${f.key}`, { defaultValue: f.fallback })}
                <InfoTip text={t(`config.sensorHelp.${f.infoKey}`)} />
              </span>
            }
            last={i === SENSOR_FIELDS.length - 1}
          >
            <EntityCombobox
              value={draft.sensors[f.key]}
              onChange={(v) => patch((d) => { d.sensors[f.key] = v })}
              entities={entitiesByDomain[f.domain]}
              domain={f.domain}
              ariaLabel={t(`config.sensor.${f.key}`, { defaultValue: f.fallback })}
            />
          </Row>
        ))}
      </Section>

      {/* Wind behaviour towards running sequences — wind blocking at start is
          configured per sequence (wind_blocks); this is the sustained-alarm
          threshold for aborting a run mid-way. */}
      <Section title={t('config.wind')}>
        <Row
          label={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
              {t('config.windAbortAfter')}
              <InfoTip text={t('config.windAbortAfterHelp')} />
            </span>
          }
          last
        >
          <NumberField
            value={draft.wind.abort_after_min}
            unit={t('config.windAbortAfterUnit')}
            min={0}
            step={0.5}
            width={90}
            aria-label={t('config.windAbortAfter')}
            onChange={(v) => patch((d) => { d.wind.abort_after_min = v })}
          />
        </Row>
      </Section>
    </div>
  )
}

const SENSOR_FIELDS: { key: keyof ConfigDoc['sensors']; domain: string; fallback: string; infoKey: string }[] = [
  { key: 'rain', domain: 'binary_sensor', fallback: 'Regen', infoKey: 'rain' },
  { key: 'wind', domain: 'binary_sensor', fallback: 'Wind', infoKey: 'wind' },
  { key: 'season', domain: 'binary_sensor', fallback: 'Saison', infoKey: 'season' },
  { key: 'temperature', domain: 'sensor', fallback: 'Temperatur', infoKey: 'temperature' },
  { key: 'temperature_max', domain: 'sensor', fallback: 'Max-Temperatur (Prognose)', infoKey: 'temperature_max' },
  { key: 'precipitation_prob_today', domain: 'sensor', fallback: 'Regenwahrscheinlichkeit heute', infoKey: 'precipitation_prob_today' },
  { key: 'precipitation_prob_tomorrow', domain: 'sensor', fallback: 'Regenwahrscheinlichkeit morgen', infoKey: 'precipitation_prob_tomorrow' },
  { key: 'precipitation_today', domain: 'sensor', fallback: 'Niederschlag heute', infoKey: 'precipitation_today' },
  { key: 'precipitation_tomorrow', domain: 'sensor', fallback: 'Niederschlag morgen', infoKey: 'precipitation_tomorrow' },
  { key: 'precipitation_actual', domain: 'sensor', fallback: 'Tatsächlicher Niederschlag', infoKey: 'precipitation_actual' },
]
