import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StalenessBanner } from './StalenessBanner'

describe('StalenessBanner', () => {
  it('renders nothing when the agent is up', () => {
    const { container } = render(<StalenessBanner agentState="up" />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the agent state is unknown', () => {
    // Unknown means "have not confirmed either way yet" (polling just
    // started, or is disabled) — not evidence of a problem, so it must not
    // read as one.
    const { container } = render(<StalenessBanner agentState="unknown" />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders a warning when the agent is down', () => {
    render(<StalenessBanner agentState="down" />)

    expect(screen.getByText('Agent unreachable — showing the last data received.')).toBeInTheDocument()
  })

  it('announces itself as a status region for assistive tech', () => {
    render(<StalenessBanner agentState="down" />)

    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
