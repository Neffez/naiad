import { createContext, useContext } from 'react'
import { type ConfigDoc, type EntityInfo } from '../../api/client'

// Shared state for every config-backed section. The draft lives in SettingsLayout
// so it survives navigation between sub-sections and the Save bar stays in sync.
export interface ConfigCtx {
  draft: ConfigDoc
  patch: (mutator: (d: ConfigDoc) => void) => void
  dirty: boolean
  entitiesByDomain: Record<string, EntityInfo[] | undefined>
  notifyServices: string[] | undefined
  requestDelete: (target: { type: 'zone' | 'sequence'; id: string }) => void
  onExport: () => void
  onImportClick: () => void
}

const Ctx = createContext<ConfigCtx | null>(null)

export const ConfigProvider = Ctx.Provider

export function useConfig(): ConfigCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useConfig must be used within a ConfigProvider')
  return ctx
}
