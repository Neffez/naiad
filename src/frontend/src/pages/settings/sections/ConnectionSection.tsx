import { useTranslation } from 'react-i18next'
import { type ConfigDoc } from '../../../api/client'
import { InfoTip } from '../../../components/InfoTip'
import { NumberField } from '../../../components/NumberField'
import { Banner, Check, EntityCombobox, Row, Section } from '../../../components/config/primitives'
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

      {/* Frost lockout: skip automatic starts when the forecast daily minimum
          is below the threshold (pipe protection in the shoulder seasons). */}
      <Section title={t('config.frost')}>
        <Row label={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            {t('config.frostEnabled')}
            <InfoTip text={t('config.frostHelp')} />
          </span>
        }>
          <Check
            label={t('config.frostEnabledHint')}
            checked={draft.frost.enabled}
            onChange={(v) => patch((d) => { d.frost.enabled = v })}
          />
        </Row>
        <Row label={t('config.frostSensor')}>
          <EntityCombobox
            value={draft.frost.temperature_min}
            onChange={(v) => patch((d) => { d.frost.temperature_min = v })}
            entities={entitiesByDomain['sensor']}
            domain="sensor"
            ariaLabel={t('config.frostSensor')}
          />
        </Row>
        <Row label={t('config.frostThreshold')} last>
          <NumberField
            value={draft.frost.threshold_c}
            unit="°C"
            step={0.5}
            width={90}
            aria-label={t('config.frostThreshold')}
            onChange={(v) => patch((d) => { d.frost.threshold_c = v })}
          />
        </Row>
        {draft.frost.enabled && !draft.frost.temperature_min && (
          <div style={{ padding: '0 20px 14px' }}>
            <Banner tone="amber">{t('config.frostSensorMissing')}</Banner>
          </div>
        )}
      </Section>

      {/* Cistern guard: skip automatic starts while the level sensor reads
          below the minimum (dry-run protection for the pump). */}
      <Section title={t('config.cistern')}>
        <Row label={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            {t('config.cisternEnabled')}
            <InfoTip text={t('config.cisternHelp')} />
          </span>
        }>
          <Check
            label={t('config.cisternEnabledHint')}
            checked={draft.cistern.enabled}
            onChange={(v) => patch((d) => { d.cistern.enabled = v })}
          />
        </Row>
        <Row label={t('config.cisternSensor')}>
          <EntityCombobox
            value={draft.cistern.level_entity}
            onChange={(v) => patch((d) => { d.cistern.level_entity = v })}
            entities={entitiesByDomain['sensor']}
            domain="sensor"
            ariaLabel={t('config.cisternSensor')}
          />
        </Row>
        <Row label={t('config.cisternMinLevel')} last>
          <NumberField
            value={draft.cistern.min_level}
            min={0}
            step={1}
            width={90}
            aria-label={t('config.cisternMinLevel')}
            onChange={(v) => patch((d) => { d.cistern.min_level = v })}
          />
        </Row>
        {draft.cistern.enabled && !draft.cistern.level_entity && (
          <div style={{ padding: '0 20px 14px' }}>
            <Banner tone="amber">{t('config.cisternSensorMissing')}</Banner>
          </div>
        )}
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
  { key: 'et0', domain: 'sensor', fallback: 'Verdunstung (ET₀)', infoKey: 'et0' },
]
