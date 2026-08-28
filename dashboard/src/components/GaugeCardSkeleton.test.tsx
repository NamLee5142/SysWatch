import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { GaugeCardSkeleton } from './GaugeCardSkeleton'

describe('GaugeCardSkeleton', () => {
  it('renders a circular placeholder sized to match the real gauge', () => {
    const { container } = render(<GaugeCardSkeleton size={160} />)

    const circle = container.querySelector('[aria-hidden="true"]') as HTMLElement
    expect(circle.style.width).toBe('160px')
    expect(circle.style.height).toBe('160px')
    expect(circle.style.borderRadius).toBe('50%')
  })

  it('renders two placeholder blocks: the ring and the hint line', () => {
    const { container } = render(<GaugeCardSkeleton />)

    expect(container.querySelectorAll('[aria-hidden="true"]')).toHaveLength(2)
  })

  it('is hidden from assistive tech entirely — purely decorative', () => {
    const { container } = render(<GaugeCardSkeleton />)

    const visible = Array.from(container.querySelectorAll('*')).filter(
      (el) => el.getAttribute('aria-hidden') !== 'true' && el.children.length === 0 && el.textContent,
    )
    expect(visible).toHaveLength(0)
  })
})
