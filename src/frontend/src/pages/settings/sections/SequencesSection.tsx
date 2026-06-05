import { useTranslation } from 'react-i18next'
import { SequenceEditor } from '../../../components/config/editors'
import { AddButton, Check, Empty, Row, Section } from '../../../components/config/primitives'
import { useConfig } from '../ConfigContext'

export default function SequencesSection() {
  const { t } = useTranslation()
  const { draft, patch, requestDelete } = useConfig()
  const zoneIds = Object.keys(draft.zones)

  return (
    <Section
      title={t('config.sequences')}
      action={
        <AddButton
          label={t('config.addSequence')}
          existing={Object.keys(draft.sequences)}
          onAdd={(id, name) => patch((d) => {
            d.sequences[id] = {
              label: name, zones: [], basis_min_per_zone: 30, range: [5, 240],
              watchdog_min: 60, schedule: { days: [], times: ['06:00'], cron: null }, enabled: false, wind_blocks: false,
              color: null,
            }
          })}
        />
      }
    >
      <Row label={t('config.sequenceColors')}>
        <Check
          label={t('config.sequenceColorsHint')}
          checked={draft.sequence_colors_enabled}
          onChange={(v) => patch((d) => { d.sequence_colors_enabled = v })}
        />
      </Row>
      {Object.keys(draft.sequences).length === 0 && (
        <Empty>{t('config.noSequences')}</Empty>
      )}
      {Object.entries(draft.sequences).map(([id, s], i, arr) => (
        <SequenceEditor
          key={id}
          id={id}
          seq={s}
          zoneIds={zoneIds}
          zones={draft.zones}
          last={i === arr.length - 1}
          colorsEnabled={draft.sequence_colors_enabled}
          onChange={(mut) => patch((d) => mut(d.sequences[id]))}
          onDelete={() => requestDelete({ type: 'sequence', id })}
        />
      ))}
    </Section>
  )
}
