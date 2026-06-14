import { useTranslation } from 'react-i18next'
import { InfoTip } from '../../../components/InfoTip'
import { NumberField } from '../../../components/NumberField'
import { AddButton, Check, EntityCombobox, Empty, Section } from '../../../components/config/primitives'
import { inputStyle } from '../../../components/config/formStyles'
import { useConfig } from '../ConfigContext'

export default function ZonesSection() {
  const { t } = useTranslation()
  const { draft, patch, entitiesByDomain, requestDelete } = useConfig()
  const zoneIds = Object.keys(draft.zones)

  return (
    <Section
      title={t('config.zones')}
      action={
        <AddButton
          label={t('config.addZone')}
          existing={zoneIds}
          onAdd={(id, name) => patch((d) => { d.zones[id] = { label: name, switch: '', flow_lph: 0, staircase_enabled: false, staircase_min: 0 } })}
        />
      }
    >
      {zoneIds.length === 0 && <Empty>{t('config.noZones')}</Empty>}

      {zoneIds.length > 0 && (
        <div className="n-zone-grid">
          {/* Column header — hidden on mobile where rows become stacked cards. */}
          <div className="n-zone-grid-row head">
            <span className="n-zone-h">ID</span>
            <span className="n-zone-h">{t('config.label')}</span>
            <span className="n-zone-h">{t('config.switch')}</span>
            <span className="n-zone-h">{t('config.flowLph')}</span>
            <span className="n-zone-h n-zone-h-stair">
              {t('config.staircase')}
              <InfoTip text={t('config.staircaseHelp')} />
            </span>
            <span className="n-zone-h" />
          </div>

          {zoneIds.map((id) => {
            const z = draft.zones[id]
            return (
              <div className="n-zone-soil-wrap" key={id}>
              <div className="n-zone-grid-row">
                <div className="n-zone-cell" data-col="id">
                  <span className="mono n-zone-id">{id}</span>
                </div>
                <div className="n-zone-cell" data-label={t('config.label')}>
                  <input style={{ ...inputStyle, width: '100%' }} value={z.label}
                    aria-label={t('config.label')}
                    onChange={(e) => patch((d) => { d.zones[id].label = e.target.value })} />
                </div>
                <div className="n-zone-cell" data-label={t('config.switch')}>
                  <EntityCombobox
                    value={z.switch}
                    onChange={(v) => patch((d) => { d.zones[id].switch = v })}
                    entities={entitiesByDomain.switch}
                    domain="switch"
                    width="100%"
                    ariaLabel={t('config.switch')}
                  />
                </div>
                <div className="n-zone-cell" data-label={t('config.flowLph')}>
                  <NumberField value={z.flow_lph} width={90}
                    aria-label={t('config.flowLph')}
                    onChange={(v) => patch((d) => { d.zones[id].flow_lph = v })} />
                </div>
                <div className="n-zone-cell n-zone-cell-stair">
                  <Check
                    label={t('config.staircaseHint')}
                    checked={z.staircase_enabled}
                    onChange={(v) => patch((d) => { d.zones[id].staircase_enabled = v })}
                  />
                  {z.staircase_enabled && (
                    <NumberField value={z.staircase_min} width={90} step={0.5} min={0}
                      aria-label={t('config.staircaseMin')}
                      onChange={(v) => patch((d) => { d.zones[id].staircase_min = v })} />
                  )}
                </div>
                <div className="n-zone-cell n-zone-cell-del">
                  <button className="n-btn" title={t('config.delete')} aria-label={t('config.delete')}
                    style={{ height: 36, width: 36, padding: 0, fontSize: 15, color: 'var(--n-danger)' }}
                    onClick={() => requestDelete({ type: 'zone', id })}>✕</button>
                </div>
              </div>
              <details className="n-zone-soil">
                <summary>
                  {t('config.soilTitle')}
                  <InfoTip text={t('config.soilHelp')} />
                </summary>
                <div className="n-zone-soil-grid">
                  <label className="n-zone-soil-field">
                    <span>{t('config.soilType')}</span>
                    <select style={{ ...inputStyle, width: '100%' }} value={z.soil_type ?? 'loam'}
                      aria-label={t('config.soilType')}
                      onChange={(e) => patch((d) => { d.zones[id].soil_type = e.target.value as 'sand' | 'loam' | 'clay' })}>
                      <option value="sand">{t('config.soilType_sand')}</option>
                      <option value="loam">{t('config.soilType_loam')}</option>
                      <option value="clay">{t('config.soilType_clay')}</option>
                    </select>
                  </label>
                  <label className="n-zone-soil-field">
                    <span>{t('config.rootDepth')}</span>
                    <NumberField value={z.root_depth_mm ?? 150} width={90} unit="mm" min={1}
                      aria-label={t('config.rootDepth')}
                      onChange={(v) => patch((d) => { d.zones[id].root_depth_mm = v })} />
                  </label>
                  <label className="n-zone-soil-field">
                    <span>{t('config.cropCoefficient')}</span>
                    <NumberField value={z.crop_coefficient ?? 1} width={70} step={0.05} min={0.05}
                      aria-label={t('config.cropCoefficient')}
                      onChange={(v) => patch((d) => { d.zones[id].crop_coefficient = v })} />
                  </label>
                  <label className="n-zone-soil-field">
                    <span>{t('config.zoneArea')}</span>
                    <NumberField value={z.area_m2 ?? 0} width={80} unit="m²" min={0}
                      aria-label={t('config.zoneArea')}
                      onChange={(v) => patch((d) => { d.zones[id].area_m2 = v })} />
                  </label>
                </div>
              </details>
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}
