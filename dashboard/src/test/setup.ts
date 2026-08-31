// Adds the DOM matchers (toBeInTheDocument, toHaveTextContent, ...) that the
// page tests read far better with, and clears the DOM between tests.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
