import { useTranslation } from 'react-i18next'
import { type ConfigDoc } from '../../../api/client'
import { InfoTip } from '../../../components/InfoTip'
import { NumberField } from '../../../components/NumberField'
import { Banner, Row, Section, StringList } from '../../../components/config/primitives'
import { inputStyle } from '../../../components/config/formStyles'
import { useConfig } from '../ConfigContext'

export default function AdvancedSection() {
  const { t } = useTranslation()
  const { draft, patch } = useConfig()

  return (
    <Section title={t('config.advanced')}>
      <Row label={t('config.timezone')}>
        <input style={{ ...inputStyle, width: 220 }} value={draft.timezone}
          aria-label={t('config.timezone')}
          onChange={(e) => patch((d) => { d.timezone = e.target.value })} />
      </Row>
      <Row label={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          {t('config.waterPrice')}
          <InfoTip text={t('config.waterPriceHelp')} />
        </span>
      }>
        <NumberField
          value={draft.water_price_per_m3}
          unit="€/m³"
          min={0}
          step={0.01}
          width={110}
          aria-label={t('config.waterPrice')}
          onChange={(v) => patch((d) => { d.water_price_per_m3 = v })}
        />
      </Row>
      <Row label={t('config.authMode')}>
        <select style={{ ...inputStyle, width: 200 }} value={draft.auth.mode}
          aria-label={t('config.authMode')}
          onChange={(e) => patch((d) => { d.auth.mode = e.target.value as ConfigDoc['auth']['mode'] })}>
          <option value="password">password</option>
          <option value="forward_header">forward_header</option>
          <option value="none">none</option>
        </select>
      </Row>
      {draft.auth.mode === 'none' && (
        <div style={{ padding: '0 20px 14px' }}>
          <Banner tone="amber">
            {t('config.authNoneWarning')}
          </Banner>
        </div>
      )}
      <Row label={t('config.frameAncestors')} last align="start">
        <StringList
          values={draft.auth.frame_ancestors}
          placeholder="'self'"
          onChange={(vals) => patch((d) => { d.auth.frame_ancestors = vals })}
        />
      </Row>
    </Section>
  )
}
