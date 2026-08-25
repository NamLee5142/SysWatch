import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  // A scaffold commit's one job is proving the toolchain runs end to end:
  // TypeScript compiles, jsdom provides a DOM, and the matchers are loaded.
  it('renders', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'SysWatch' })).toBeInTheDocument()
  })
})
