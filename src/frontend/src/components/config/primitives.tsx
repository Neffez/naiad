import { type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { type EntityInfo } from '../../api/client'
import { NumberField } from '../NumberField'
import { inputStyle } from './formStyles'

// ── Small reusable building blocks ──────────────────────────────────────────────

export function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      border: '1px solid var(--n-line)', borderRadius: 'var(--n-r-lg)', overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 20px', background: 'var(--n-surface-overlay)',
        borderBottom: '1px solid var(--n-line)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
      }}>
        <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  )
}

export function Row({ label, children, last = false, align = 'center' }: {
  label: ReactNode; children: ReactNode; last?: boolean; align?: 'center' | 'start'
}) {
  return (
    <div className="n-cfg-row" style={{
      display: 'flex', alignItems: align === 'start' ? 'flex-start' : 'center',
      justifyContent: 'space-between', gap: 16,
      padding: '12px 20px', borderBottom: last ? 'none' : '1px solid var(--n-line)', minHeight: 52,
    }}>
      <span style={{ fontSize: 14, color: 'var(--n-fg-soft)', paddingTop: align === 'start' ? 6 : 0 }}>{label}</span>
      <div className="n-cfg-control" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>{children}</div>
    </div>
  )
}

export function CardRow({ children, last }: { children: ReactNode; last: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap',
      padding: '14px 20px', borderBottom: last ? 'none' : '1px solid var(--n-line)',
    }}>
      {children}
    </div>
  )
}

export function Labeled({ label, children, align = 'center' }: { label: ReactNode; children: ReactNode; align?: 'center' | 'start' }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: align === 'start' ? 'flex-start' : undefined }}>
      <span style={{ fontSize: 11, color: 'var(--n-fg-muted)', letterSpacing: '0.02em' }}>{label}</span>
      {children}
    </label>
  )
}

export function IdTag({ id }: { id: string }) {
  return (
    <span className="mono" style={{
      fontSize: 12, color: 'var(--n-teal-200)',
      background: 'var(--n-teal-glow)', border: '1px solid var(--n-glow-border)',
      padding: '4px 8px', borderRadius: 'var(--n-r-sm)',
      marginTop: 18,
    }}>{id}</span>
  )
}

export function Num({ value, step = 1, onChange, ariaLabel }: { value: number; step?: number; onChange: (v: number) => void; ariaLabel?: string }) {
  return <NumberField value={value} step={step} width={90} aria-label={ariaLabel} onChange={onChange} />
}

export function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (c: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', fontSize: 13, color: 'var(--n-fg-muted)', userSelect: 'none' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        style={{ width: 16, height: 16, accentColor: 'var(--n-teal-400)', cursor: 'pointer' }} />
      {label}
    </label>
  )
}

export function StringList({ values, placeholder, onChange }: {
  values: string[]; placeholder?: string; onChange: (vals: string[]) => void
}) {
  const { t } = useTranslation()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', maxWidth: 344 }}>
      {values.map((v, i) => (
        <div key={i} style={{ display: 'flex', gap: 6 }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 0 }} value={v} placeholder={placeholder}
            aria-label={placeholder}
            onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))} />
          <DeleteButton onClick={() => onChange(values.filter((_, j) => j !== i))} />
        </div>
      ))}
      <button className="n-btn" style={{ height: 32, padding: '0 12px', fontSize: 12.5, alignSelf: 'flex-start' }}
        onClick={() => onChange([...values, ''])}>
        + {t('config.addEntry')}
      </button>
    </div>
  )
}

// Derive an internal snake_case id from a human name. Umlauts/diacritics are
// stripped (NFKD), everything non-alphanumeric collapses to single underscores.
function slugify(name: string): string {
  return name
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

// Ensure the generated id doesn't collide with an existing one.
function uniqueId(base: string, existing: string[]): string {
  const root = base || 'item'
  if (!existing.includes(root)) return root
  let n = 2
  while (existing.includes(`${root}_${n}`)) n++
  return `${root}_${n}`
}

export function AddButton({ label, existing, onAdd }: {
  label: string; existing: string[]; onAdd: (id: string, name: string) => void
}) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  // The user types a name; the id is generated for them. Valid as long as the
  // name yields a non-empty slug.
  const valid = slugify(name).length > 0
  function submit() {
    if (!valid) return
    onAdd(uniqueId(slugify(name), existing), name.trim())
    setName('')
    setAdding(false)
  }
  if (!adding) {
    return (
      <button className="n-btn" style={{ height: 32, padding: '0 12px', fontSize: 12.5 }} onClick={() => setAdding(true)}>
        + {label}
      </button>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <input autoFocus style={{ ...inputStyle, width: 180, height: 32 }} value={name}
        placeholder={t('config.namePlaceholder')}
        aria-label={t('config.namePlaceholder')}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') submit() }} />
      <button className="n-btn primary" disabled={!valid} style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
        onClick={submit}>
        {t('config.add')}
      </button>
      <button className="n-btn" title={t('config.cancel')} aria-label={t('config.cancel')}
        style={{ height: 32, padding: '0 10px', fontSize: 12.5 }}
        onClick={() => { setName(''); setAdding(false) }}>✕</button>
    </div>
  )
}

export function DeleteButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button className="n-btn" title={t('config.delete')} aria-label={t('config.delete')}
      style={{ height: 36, width: 36, padding: 0, fontSize: 15, color: 'var(--n-danger)', marginTop: 18 }}
      onClick={onClick}>✕</button>
  )
}

// Searchable entity picker populated from Home Assistant. Filters by friendly
// name or entity_id as you type, shows a type hint, and still accepts a pasted /
// typed entity_id that isn't in the list. The dropdown is portalled to <body> so
// the Section's `overflow: hidden` can't clip it.
export type ComboOption = { value: string; label: string; sub?: string }

function entityOptions(entities?: EntityInfo[]): ComboOption[] {
  return (entities ?? []).map((e) => ({
    value: e.entity_id,
    label: e.friendly_name || e.entity_id,
    sub: e.friendly_name ? e.entity_id : undefined,
  }))
}

// Searchable picker. Pass either `entities` (HA entities, with a type hint from
// `domain`) or a ready-made `options` list (e.g. notify services) plus a `hint`.
export function EntityCombobox({ value, onChange, entities, options, domain, hint, width = 320, ariaLabel }: {
  value: string
  onChange: (v: string) => void
  entities?: EntityInfo[]
  options?: ComboOption[]
  domain?: string
  hint?: string
  width?: number
  ariaLabel?: string
}) {
  const { t } = useTranslation()
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [rect, setRect] = useState<DOMRect | null>(null)

  const list = options ?? entityOptions(entities)
  const q = query.trim().toLowerCase()
  const matches = (
    q
      ? list.filter(
          (o) =>
            o.value.toLowerCase().includes(q) ||
            o.label.toLowerCase().includes(q) ||
            (o.sub?.toLowerCase().includes(q) ?? false),
        )
      : list
  ).slice(0, 50)
  const hintText = hint ?? (domain ? t(`config.entityType.${domain}`, { defaultValue: domain }) : '')

  function reposition() {
    if (inputRef.current) setRect(inputRef.current.getBoundingClientRect())
  }

  useEffect(() => {
    if (!open) return
    const onScroll = () => reposition()
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (wrapRef.current?.contains(target)) return
      if (document.getElementById('entity-combobox-pop')?.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  function choose(o: ComboOption) {
    onChange(o.value)
    setQuery('')
    setOpen(false)
  }

  // Commit free text only if it looks like an entity id (so an abandoned search
  // term doesn't overwrite the saved value).
  function commitFreeText() {
    if (query && query.includes('.') && query !== value) onChange(query)
    setOpen(false)
  }

  const looksLikeId = q.includes('.')

  return (
    <div ref={wrapRef} style={{ width, maxWidth: '100%', display: 'flex', flexDirection: 'column', gap: 3 }}>
      <input
        ref={inputRef}
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches[active] ? `${listboxId}-opt-${active}` : undefined}
        aria-label={ariaLabel}
        style={{ ...inputStyle, width: '100%' }}
        value={open ? query : value}
        placeholder={
          open && value ? value : t('config.entitySearch')
        }
        onFocus={() => { setQuery(''); setActive(0); reposition(); setOpen(true) }}
        onChange={(e) => { setQuery(e.target.value); setActive(0); if (!open) { reposition(); setOpen(true) } }}
        onBlur={() => { if (open) commitFreeText() }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, matches.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          else if (e.key === 'Enter') {
            if (open && matches[active]) { e.preventDefault(); choose(matches[active]) }
            else if (looksLikeId) { e.preventDefault(); commitFreeText() }
          } else if (e.key === 'Escape') { setQuery(''); setOpen(false) }
        }}
      />
      {hintText && (
        <span style={{ fontSize: 10.5, color: 'var(--n-fg-dim)', letterSpacing: '0.02em' }}>
          {t('config.expects')}: {hintText}
        </span>
      )}
      {open && rect && createPortal(
        <div
          id={listboxId}
          role="listbox"
          className="n-card"
          style={{
            position: 'fixed', top: rect.bottom + 4, left: rect.left, width: rect.width,
            maxHeight: 260, overflowY: 'auto', padding: 4, zIndex: 1000,
          }}
        >
          {matches.length === 0 ? (
            <div style={{ padding: '8px 10px', fontSize: 12.5, color: 'var(--n-fg-muted)' }}>
              {t('config.noEntities')}
            </div>
          ) : (
            matches.map((o, i) => (
              <button
                key={o.value}
                id={`${listboxId}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                type="button"
                onMouseEnter={() => setActive(i)}
                onMouseDown={(ev) => { ev.preventDefault(); choose(o) }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px',
                  background: i === active ? 'var(--n-teal-glow)' : 'transparent',
                  border: 0, borderRadius: 6, cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 13, color: 'var(--n-fg)' }}>{o.label}</div>
                {o.sub && (
                  <div className="mono" style={{ fontSize: 11, color: 'var(--n-fg-muted)' }}>{o.sub}</div>
                )}
              </button>
            ))
          )}
        </div>,
        document.body,
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--n-fg-dim)' }}>{children}</div>
}

export function Pill({ tone, children }: { tone: 'teal' | 'muted'; children: ReactNode }) {
  const teal = tone === 'teal'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 999,
      fontSize: 12.5, fontWeight: 500,
      background: teal ? 'var(--n-teal-glow)' : 'transparent',
      border: `1px solid ${teal ? 'var(--n-glow-border)' : 'var(--n-line-strong)'}`,
      color: teal ? 'var(--n-teal-200)' : 'var(--n-fg-muted)',
    }}>{children}</span>
  )
}

export function Banner({ tone, children }: { tone: 'amber' | 'danger'; children: ReactNode }) {
  const amber = tone === 'amber'
  return (
    <div style={{
      padding: '12px 16px', borderRadius: 'var(--n-r-md, 12px)', fontSize: 13,
      background: amber ? 'rgba(217,166,72,0.10)' : 'rgba(196,90,90,0.10)',
      border: `1px solid ${amber ? 'var(--n-paused)' : 'var(--n-danger)'}`,
      color: amber ? 'var(--n-paused)' : 'var(--n-danger)',
    }}>{children}</div>
  )
}
