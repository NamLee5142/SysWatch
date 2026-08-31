import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AgentState } from '../api/types'
import { StatusDot } from './StatusDot'

const STATES: AgentState[] = ['up', 'down', 'unknown']

function classNameFor(state: AgentState): string | undefined {
  const { container } = render(<StatusDot state={state} />)
  return container.querySelector('span')?.className
}

describe('StatusDot', () => {
  it('renders a distinct class per state, so each is visually distinguishable', () => {
    const classNames = STATES.map(classNameFor)

    expect(new Set(classNames).size).toBe(STATES.length)
  })

  it('is hidden from assistive tech, since it is always paired with a text label', () => {
    const { container } = render(<StatusDot state="up" />)

    expect(container.querySelector('span')).toHaveAttribute('aria-hidden', 'true')
  })
})
