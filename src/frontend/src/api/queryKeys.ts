/**
 * Central registry of React Query keys.
 *
 * Using these instead of inline string literals keeps fetch and
 * `invalidateQueries` calls in sync — a typo becomes a compile error rather than
 * a silently stale cache. Parameterized keys (history page, entity/service
 * domain) are factory functions; their bare prefixes (e.g. `history`) are kept
 * for prefix-based invalidation across all pages.
 */
export const queryKeys = {
  sequences: ['sequences'] as const,
  status: ['status'] as const,
  config: ['config'] as const,
  valves: ['valves'] as const,
  settings: ['settings'] as const,
  preferences: ['preferences'] as const,
  plans: ['plans'] as const,
  // Week view shares the 'plans' prefix so creating/deleting a plan
  // invalidates it too.
  upcomingRuns: (days: number) => ['plans', 'upcoming', days] as const,
  health: ['health'] as const,
  history: ['history'] as const,
  historyPage: (page: number, filters?: Record<string, string | undefined>) =>
    ['history', page, filters ?? {}] as const,
  // Server-side aggregate for the history summary bar, independent of filters.
  historySummary: (days: number) => ['history', 'summary', days] as const,
  // Decision log pages share the 'history' prefix so deleting the history
  // invalidates them too.
  decisionsPage: (page: number, sequenceId?: string) =>
    ['history', 'decisions', page, sequenceId ?? ''] as const,
  entities: (domain: string) => ['entities', domain] as const,
  services: (domain: string) => ['services', domain] as const,
} as const
