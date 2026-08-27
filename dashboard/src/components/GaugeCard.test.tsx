import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { GaugeCard } from './GaugeCard'

describe('GaugeCard', () => {
  it('renders the gauge reading', () => {
    render(<GaugeCard value={63.4} />)

    expect(screen.getByText('63%')).toBeInTheDocument()
  })

  it('renders a label when provided', () => {
    render(<GaugeCard value={50} label="CPU" />)

    expect(screen.getByText('CPU')).toBeInTheDocument()
  })

  it('omits the label and hint elements entirely when neither is provided', () => {
    const { container: bare } = render(<GaugeCard value={50} />)
    const { container: withHint } = render(<GaugeCard value={50} hint="8 cores" />)

    // Gauge's own readout always renders one <span> (the percentage); a
    // caller that passed neither label nor hint should not add any more,
    // and one that passed only a hint should add exactly one.
    expect(bare.querySelectorAll('span')).toHaveLength(1)
    expect(withHint.querySelectorAll('span')).toHaveLength(2)
  })

  it('renders a hint when provided', () => {
    render(<GaugeCard value={50} hint="8 cores" />)

    expect(screen.getByText('8 cores')).toBeInTheDocument()
  })

  it('passes size through to the underlying gauge', () => {
    render(<GaugeCard value={50} size={160} />)

    const svg = document.querySelector('svg')
    expect(svg).toHaveAttribute('width', '160')
    expect(svg).toHaveAttribute('height', '160')
  })
})
