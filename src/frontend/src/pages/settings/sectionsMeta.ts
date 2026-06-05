// Section taxonomy for the unified settings area. Each section is its own route
// under /settings and belongs to a navigation group. `usesDraft` marks sections
// backed by the config draft (explicit Save) versus the settings/local domains
// that persist immediately.

export type SectionId =
  | 'zones'
  | 'sequences'
  | 'watering'
  | 'notifications'
  | 'connection'
  | 'integrations'
  | 'advanced'
  | 'system'

export type SectionGroup = 'operation' | 'setup' | 'system'

export interface SectionMeta {
  id: SectionId
  group: SectionGroup
  usesDraft: boolean
}

export const SECTIONS: SectionMeta[] = [
  { id: 'zones', group: 'operation', usesDraft: true },
  { id: 'sequences', group: 'operation', usesDraft: true },
  { id: 'watering', group: 'operation', usesDraft: false },
  { id: 'notifications', group: 'operation', usesDraft: true },
  { id: 'connection', group: 'setup', usesDraft: true },
  { id: 'integrations', group: 'setup', usesDraft: true },
  { id: 'advanced', group: 'setup', usesDraft: true },
  { id: 'system', group: 'system', usesDraft: false },
]

export const GROUP_ORDER: SectionGroup[] = ['operation', 'setup', 'system']

// The landing section when navigating to /settings.
export const DEFAULT_SECTION: SectionId = 'zones'
