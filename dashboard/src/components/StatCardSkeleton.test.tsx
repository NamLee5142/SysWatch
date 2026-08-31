import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatCardSkeleton } from './StatCardSkeleton'

describe('StatCardSkeleton', () => {
  it('renders a label-height line and a taller value-height line', () => {
    const { container } = render(<StatCardSkeleton />)

    const blocks = container.querySelectorAll('[aria-hidden="true"]')
    expect(blocks).toHaveLength(2)
  })

  it('stacks the two lines vertically, not side by side', () => {
    // .card has no flex layout of its own (unlike GaugeCard's); each line
    // must be wrapped in its own block-level element or they would render
    // inline, side by side, instead of stacked like the real StatCard.
    const { container } = render(<StatCardSkeleton />)

    const paragraphs = container.querySelectorAll('p')
    expect(paragraphs).toHaveLength(2)
    expect(paragraphs[0].querySelector('[aria-hidden="true"]')).toBeInTheDocument()
    expect(paragraphs[1].querySelector('[aria-hidden="true"]')).toBeInTheDocument()
  })
})
