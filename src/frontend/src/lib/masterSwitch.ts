/** Effective master-switch state for the UI.

 * When `/api/status` has not loaded (or failed), do **not** default to on.
 * A missing status used to render the switch as on and every click sent
 * `{on: false}` — so a backend that was actually off could never be turned on.
 */
export function masterSwitchOn(status: { master_on: boolean } | undefined): boolean {
  return status?.master_on ?? false
}
