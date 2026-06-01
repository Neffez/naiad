import { type CSSProperties, useEffect, useRef, useState } from 'react'
import { IChev } from './icons'

interface BaseProps {
  step?: number
  min?: number
  max?: number
  unit?: string
  /** Fixed input width in px. Ignored when `fullWidth`. Default 72. */
  width?: number
  /** Stretch to fill the parent (input flexes); used for the larger form layout. */
  fullWidth?: boolean
  /** 'sm' = compact (settings/config, h36); 'lg' = form field (planner, h52). */
  size?: 'sm' | 'lg'
  placeholder?: string
  disabled?: boolean
  /** Focus (and select) the input on mount — used for inline click-to-edit. */
  autoFocus?: boolean
  /** Extra styles merged onto the outer wrapper. */
  style?: CSSProperties
  'aria-label'?: string
}

type NumberFieldProps = BaseProps & (
  // Numeric mode: always holds a number.
  | { value: number; onChange: (v: number) => void; allowEmpty?: false }
  // String mode: may be empty (""), e.g. an optional override. onChange emits a string.
  | { value: string; onChange: (v: string) => void; allowEmpty: true }
)

/** Decimal places implied by the step, so 0.1 + 0.2 doesn't show 0.30000000004. */
function decimalsOf(step: number): number {
  const s = String(step)
  const i = s.indexOf('.')
  return i === -1 ? 0 : s.length - i - 1
}

function clamp(n: number, min?: number, max?: number): number {
  if (min !== undefined && n < min) return min
  if (max !== undefined && n > max) return max
  return n
}

/**
 * Themed number input with custom up/down steppers.
 *
 * Replaces the native `<input type="number">` whose browser spinner arrows
 * don't follow the app theme. The native spinners are hidden (see `.n-num-input`
 * in index.css) and replaced by chevron buttons that match `--n-*` tokens.
 *
 * The text value is edited freely as a string and committed on blur / Enter;
 * the stepper buttons commit immediately. Values are clamped to min/max and
 * rounded to the precision implied by `step`.
 *
 * Modes:
 *  - numeric (default): `value` is a number, `onChange` receives a number.
 *  - `allowEmpty`: `value` is a string that may be "" (optional fields); the
 *    `onChange` callback receives a string so the empty state round-trips.
 */
export function NumberField(props: NumberFieldProps) {
  const {
    step = 1, min, max, unit, width = 72, fullWidth = false,
    size = 'sm', placeholder, disabled = false, style,
    autoFocus = false,
    'aria-label': ariaLabel,
  } = props

  const [local, setLocal] = useState(String(props.value))
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (autoFocus) { inputRef.current?.focus(); inputRef.current?.select() }
    // Focus only on mount — autoFocus is a one-shot intent, not a reactive value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keep the field in sync when the value changes from outside (e.g. reset).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setLocal(String(props.value)) }, [props.value])

  const decimals = decimalsOf(step)
  const lg = size === 'lg'

  const emit = (raw: number | '') => {
    if (props.allowEmpty) props.onChange(raw === '' ? '' : String(raw))
    else if (raw !== '') props.onChange(raw)
  }

  const normalize = (n: number): number => {
    const c = clamp(n, min, max)
    return decimals > 0 ? Number(c.toFixed(decimals)) : c
  }

  const commit = (raw: string) => {
    if (raw.trim() === '') {
      if (props.allowEmpty) { setLocal(''); emit('') }
      else setLocal(String(props.value))
      return
    }
    const n = parseFloat(raw)
    if (isNaN(n)) {
      setLocal(props.allowEmpty ? String(props.value || '') : String(props.value))
      return
    }
    const rounded = normalize(n)
    setLocal(String(rounded))
    emit(rounded)
  }

  const bump = (dir: 1 | -1) => {
    const base = parseFloat(local)
    const start = isNaN(base) ? (typeof props.value === 'number' ? props.value : min ?? 0) : base
    const rounded = normalize(start + dir * step)
    setLocal(String(rounded))
    emit(rounded)
    inputRef.current?.focus()
  }

  const numericValue = parseFloat(local)
  const atMax = max !== undefined && !isNaN(numericValue) && numericValue >= max
  const atMin = min !== undefined && !isNaN(numericValue) && numericValue <= min

  return (
    <div
      style={{
        display: fullWidth ? 'flex' : 'inline-flex',
        alignItems: 'stretch',
        width: fullWidth ? '100%' : undefined,
        background: lg ? 'var(--n-card)' : 'var(--n-card-elev)',
        border: '1px solid var(--n-line-strong)',
        borderRadius: lg ? 'var(--n-r-md)' : 'var(--n-r-sm)',
        overflow: 'hidden', height: lg ? 52 : 36,
        opacity: disabled ? 0.5 : 1,
        ...style,
      }}
    >
      <input
        ref={inputRef}
        className="n-num-input"
        type="number"
        inputMode="decimal"
        value={local}
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(e) => {
          setLocal(e.target.value)
          // In allowEmpty mode the parent stores the raw string, so keep it live.
          if (props.allowEmpty) props.onChange(e.target.value)
        }}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { commit((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).blur() }
          else if (e.key === 'ArrowUp') { e.preventDefault(); bump(1) }
          else if (e.key === 'ArrowDown') { e.preventDefault(); bump(-1) }
        }}
        style={{
          width: fullWidth ? undefined : width,
          flex: fullWidth ? 1 : undefined,
          height: '100%', padding: lg ? '0 18px' : '0 10px',
          background: 'transparent', border: 'none',
          color: 'var(--n-fg)', fontSize: lg ? 15 : 14,
          fontFamily: 'var(--n-sans)',
          fontVariantNumeric: 'tabular-nums',
          textAlign: fullWidth ? 'left' : 'right', outline: 'none',
          minWidth: 0,
        }}
      />
      {unit && (
        <span style={{
          padding: lg ? '0 14px' : '0 8px',
          color: 'var(--n-fg-muted)', fontSize: lg ? 13 : 12,
          borderLeft: '1px solid var(--n-line)',
          display: 'flex', alignItems: 'center',
          background: 'rgba(255,255,255,0.015)',
          whiteSpace: 'nowrap',
        }}>
          {unit}
        </span>
      )}
      <div style={{
        display: 'flex', flexDirection: 'column',
        borderLeft: '1px solid var(--n-line)',
      }}>
        <StepBtn dir="up" lg={lg} disabled={disabled || atMax} onClick={() => bump(1)} />
        <StepBtn dir="down" lg={lg} disabled={disabled || atMin} onClick={() => bump(-1)} />
      </div>
    </div>
  )
}

function StepBtn({ dir, lg, disabled, onClick }: {
  dir: 'up' | 'down'; lg: boolean; disabled: boolean; onClick: () => void
}) {
  const [hover, setHover] = useState(false)
  return (
    <button
      type="button"
      tabIndex={-1}
      disabled={disabled}
      aria-hidden="true"
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        flex: 1, width: lg ? 28 : 22, padding: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: hover && !disabled ? 'rgba(94,200,216,0.12)' : 'transparent',
        border: 'none',
        borderBottom: dir === 'up' ? '1px solid var(--n-line)' : 'none',
        color: disabled ? 'var(--n-fg-muted)' : 'var(--n-fg)',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transition: 'background 0.12s',
      }}
    >
      <IChev size={lg ? 13 : 12} style={{ transform: dir === 'up' ? 'rotate(-90deg)' : 'rotate(90deg)' }} />
    </button>
  )
}
