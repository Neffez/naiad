import type { SVGProps } from 'react'

interface IconProps extends SVGProps<SVGSVGElement> {
  size?: number
}

function Icon({ size = 18, children, className = '', style, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

export function IPlay(p: IconProps) {
  return <Icon {...p}><polygon points="6 4 20 12 6 20 6 4" /></Icon>
}

export function IPause(p: IconProps) {
  return (
    <Icon {...p}>
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </Icon>
  )
}

export function ICal(p: IconProps) {
  return (
    <Icon {...p}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 9h18" />
      <path d="M8 3v4M16 3v4" />
    </Icon>
  )
}

export function IStop(p: IconProps) {
  return <Icon {...p}><rect x="6" y="6" width="12" height="12" rx="1.5" /></Icon>
}

export function IBolt(p: IconProps) {
  return <Icon {...p}><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" /></Icon>
}

export function ISun(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </Icon>
  )
}

export function IDrop(p: IconProps) {
  return <Icon {...p}><path d="M12 3s6 7 6 11a6 6 0 1 1-12 0c0-4 6-11 6-11Z" /></Icon>
}

export function IWind(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M3 8h11a3 3 0 1 0-3-3M3 12h17a3 3 0 1 1-3 3M3 16h9a3 3 0 1 0-3 3" />
    </Icon>
  )
}

export function IGauge(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M12 14 17 9" />
      <path d="M3 19a9 9 0 1 1 18 0" />
    </Icon>
  )
}

export function IChev(p: IconProps) {
  return <Icon {...p}><polyline points="9 6 15 12 9 18" /></Icon>
}

export function IChevDown(p: IconProps) {
  return <Icon {...p}><polyline points="6 9 12 15 18 9" /></Icon>
}

export function IHome(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M3 11 12 3l9 8" />
      <path d="M5 10v10h14V10" />
    </Icon>
  )
}

export function IList(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <circle cx="4" cy="6" r="1" />
      <circle cx="4" cy="12" r="1" />
      <circle cx="4" cy="18" r="1" />
    </Icon>
  )
}

export function IChart(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M3 3v18h18" />
      <path d="M7 15l4-4 3 3 5-6" />
    </Icon>
  )
}

export function ISettings(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </Icon>
  )
}

export function IAlert(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M12 9v4M12 17h.01" />
      <path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0Z" />
    </Icon>
  )
}

export function IX(p: IconProps) {
  return <Icon {...p}><path d="M18 6 6 18M6 6l12 12" /></Icon>
}

export function IClock(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15 14" />
    </Icon>
  )
}

export function IArrow(p: IconProps) {
  return (
    <Icon {...p}>
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </Icon>
  )
}

export function ICheck(p: IconProps) {
  return <Icon {...p}><polyline points="20 6 9 17 4 12" /></Icon>
}

export function ICloud(p: IconProps) {
  return <Icon {...p}><path d="M17 18a4 4 0 0 0 0-8 6 6 0 0 0-11.7-1A4 4 0 0 0 6 17" /></Icon>
}

export function ISnow(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M2 12h20M12 2v20" />
      <path d="m20 16-4-4 4-4M4 8l4 4-4 4M16 4l-4 4-4-4M8 20l4-4 4 4" />
    </Icon>
  )
}

export function IMoon(p: IconProps) {
  return <Icon {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></Icon>
}

export function ILogo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 124 153" fill="none" aria-hidden="true">
      <path d="M62 0 C62 0 116 63 116 100 C116 131 92 153 62 153 C32 153 8 131 8 100 C8 63 62 0 62 0 Z" fill="#1a7a8a" />
      <path d="M20 100 C32 90 50 95 62 90 C74 85 88 90 104 100" fill="none" stroke="#5ec8d8" strokeWidth="3" strokeLinecap="round" opacity="0.85" />
      <path d="M16 116 C30 105 50 111 62 106 C74 101 90 106 108 116" fill="none" stroke="#b8eaf2" strokeWidth="2.2" strokeLinecap="round" opacity="0.55" />
    </svg>
  )
}
