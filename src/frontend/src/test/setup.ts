import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Unmount React trees and clear localStorage between tests so state never leaks
// from one test into the next.
afterEach(() => {
  cleanup()
  localStorage.clear()
})
