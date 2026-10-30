import { describe, expect, it } from 'vitest'
import { masterSwitchOn } from './masterSwitch'

describe('masterSwitchOn', () => {
  it('uses the status value when it has loaded', () => {
    expect(masterSwitchOn({ master_on: true })).toBe(true)
    expect(masterSwitchOn({ master_on: false })).toBe(false)
  })

  it('defaults to off when status has not loaded, so a click turns watering on', () => {
    expect(masterSwitchOn(undefined)).toBe(false)
  })
})
