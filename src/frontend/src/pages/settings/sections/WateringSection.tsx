import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clearFactorOverrides, getSettings, updateSettings } from '../../../api/client'
import { queryKeys } from '../../../api/queryKeys'
import { InfoTip } from '../../../components/InfoTip'
import { NumberField } from '../../../components/NumberField'
import { Row, Section } from '../../../components/config/primitives'

// Watering factors live in the settings (FactorOverride) domain and persist
// immediately on change — independent of the config draft / Save bar.
export default function WateringSection() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: queryKeys.settings, queryFn: getSettings })
  const [saved, setSaved] = useState(false)

  function onSaved() {
    qc.invalidateQueries({ queryKey: queryKeys.settings })
    qc.invalidateQueries({ queryKey: queryKeys.sequences })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const mut = useMutation({ mutationFn: updateSettings, onSuccess: onSaved })
  const resetMut = useMutation({ mutationFn: clearFactorOverrides, onSuccess: onSaved })

  if (!settings) return (
    <div style={{ padding: 20, color: 'var(--n-fg-muted)' }}>{t('settings.loading')}</div>
  )

  const rain = settings.factors.rain
  const temp = settings.factors.temp

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {saved && (
        <div style={{
          display: 'inline-flex', alignSelf: 'flex-start', alignItems: 'center', gap: 8,
          padding: '8px 16px', borderRadius: 999,
          background: 'var(--n-teal-glow)', border: '1px solid var(--n-glow-border)',
          color: 'var(--n-teal-200)', fontSize: 13, fontWeight: 500,
        }}>
          ✓ {t('settings.saved')}
        </div>
      )}

      <Section
        title={t('settings.factorTemp')}
        action={settings.factors.temp_overridden ? (
          <ResetAction disabled={resetMut.isPending} onReset={() => resetMut.mutate('temp')} />
        ) : undefined}
      >
        <FactorRow label={t('settings.basisC')} info={t('settings.help.basisC')}>
          <NumberField value={temp.basis_c} unit="°C" aria-label={t('settings.basisC')} onChange={(v) => mut.mutate({ factors: { temp: { basis_c: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.pctPerC')} info={t('settings.help.pctPerC')}>
          <NumberField value={temp.pct_per_c} unit="%" aria-label={t('settings.pctPerC')} onChange={(v) => mut.mutate({ factors: { temp: { pct_per_c: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.minPct')} info={t('settings.help.minPct')}>
          <NumberField value={temp.min_pct} unit="%" aria-label={t('settings.minPct')} onChange={(v) => mut.mutate({ factors: { temp: { min_pct: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.maxPct')} info={t('settings.help.maxPct')} last>
          <NumberField value={temp.max_pct} unit="%" aria-label={t('settings.maxPct')} onChange={(v) => mut.mutate({ factors: { temp: { max_pct: v } } })} />
        </FactorRow>
      </Section>

      <Section
        title={t('settings.factorRain')}
        action={settings.factors.rain_overridden ? (
          <ResetAction disabled={resetMut.isPending} onReset={() => resetMut.mutate('rain')} />
        ) : undefined}
      >
        <FactorRow label={t('settings.rainMode')} info={t('settings.help.rainMode')}>
          <ButtonGroup
            label={t('settings.rainMode')}
            options={(['forecast', 'water_balance'] as const).map((val) => ({
              value: val, active: rain.mode === val, label: t(`settings.rainMode_${val}`),
              onClick: () => mut.mutate({ factors: { rain: { mode: val } } }),
            }))}
          />
        </FactorRow>
        <FactorRow label={t('settings.thresholdProb')} info={t('settings.help.thresholdProb')}>
          <NumberField value={rain.threshold_prob} unit="%" aria-label={t('settings.thresholdProb')} onChange={(v) => mut.mutate({ factors: { rain: { threshold_prob: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.reduceAbove')} info={t('settings.help.reduceAbove')}>
          <NumberField value={rain.reduce_above_mm} unit="mm" aria-label={t('settings.reduceAbove')} onChange={(v) => mut.mutate({ factors: { rain: { reduce_above_mm: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.zeroAbove')} info={t('settings.help.zeroAbove')}>
          <NumberField value={rain.zero_above_mm} unit="mm" aria-label={t('settings.zeroAbove')} onChange={(v) => mut.mutate({ factors: { rain: { zero_above_mm: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.forecastDecay')} info={t('settings.help.forecastDecay')}>
          <NumberField value={rain.forecast_decay} width={60} step={0.1} aria-label={t('settings.forecastDecay')} onChange={(v) => mut.mutate({ factors: { rain: { forecast_decay: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.waterBalanceDays')} info={t('settings.help.waterBalanceDays')}>
          <NumberField value={rain.water_balance_days} unit="d" width={60} aria-label={t('settings.waterBalanceDays')} onChange={(v) => mut.mutate({ factors: { rain: { water_balance_days: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.waterBalanceDecay')} info={t('settings.help.waterBalanceDecay')}>
          <NumberField value={rain.water_balance_decay} width={60} step={0.05} aria-label={t('settings.waterBalanceDecay')} onChange={(v) => mut.mutate({ factors: { rain: { water_balance_decay: v } } })} />
        </FactorRow>
        <FactorRow label={t('settings.peakTomorrow')} info={t('settings.help.peakTomorrow')}>
          <ButtonGroup
            label={t('settings.peakTomorrow')}
            options={([false, true] as const).map((val) => ({
              value: String(val), active: rain.peak_tomorrow === val,
              label: val ? t('settings.peakTomorrow_both') : t('settings.peakTomorrow_today'),
              onClick: () => mut.mutate({ factors: { rain: { peak_tomorrow: val } } }),
            }))}
          />
        </FactorRow>
        <FactorRow label={t('settings.confirmRainSensor')} info={t('settings.help.confirmRainSensor')} last>
          <ButtonGroup
            label={t('settings.confirmRainSensor')}
            options={([false, true] as const).map((val) => ({
              value: String(val), active: rain.confirm_with_rain_sensor === val,
              label: val ? t('settings.confirmRainSensor_on') : t('settings.confirmRainSensor_off'),
              onClick: () => mut.mutate({ factors: { rain: { confirm_with_rain_sensor: val } } }),
            }))}
          />
        </FactorRow>
      </Section>
    </div>
  )
}

function FactorRow({ label, info, children, last }: { label: string; info: string; children: ReactNode; last?: boolean }) {
  return (
    <Row
      last={last}
      label={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          {label}
          <InfoTip text={info} />
        </span>
      }
    >
      {children}
    </Row>
  )
}

// Shown in a factor section header only when that group has overrides. Frames the
// override as a positive, reversible state ("customized → reset") rather than a
// hidden mechanism.
function ResetAction({ onReset, disabled }: { onReset: () => void; disabled: boolean }) {
  const { t } = useTranslation()
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--n-fg-dim)', letterSpacing: '0.02em' }}>
        {t('settings.customized')}
      </span>
      <button
        className="n-btn"
        disabled={disabled}
        style={{ height: 28, padding: '0 10px', fontSize: 12 }}
        onClick={onReset}
      >
        {t('settings.resetDefaults')}
      </button>
    </div>
  )
}

function ButtonGroup({ label, options }: {
  label: string
  options: { value: string; active: boolean; label: string; onClick: () => void }[]
}) {
  return (
    <div role="group" aria-label={label} style={{ display: 'flex', gap: 6 }}>
      {options.map((o) => (
        <button
          key={o.value}
          className={`n-btn${o.active ? ' primary' : ''}`}
          aria-pressed={o.active}
          style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
          onClick={o.onClick}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
