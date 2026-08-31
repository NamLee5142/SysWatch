import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Skeleton } from './Skeleton'

describe('Skeleton', () => {
  it('is hidden from assistive tech', () => {
    const { container } = render(<Skeleton />)

    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true')
  })

  it('applies the given width and height as inline styles', () => {
    const { container } = render(<Skeleton width={120} height={16} />)

    const el = container.firstChild as HTMLElement
    expect(el.style.width).toBe('120px')
    expect(el.style.height).toBe('16px')
  })

  it('defaults to a full-width, text-height line', () => {
    const { container } = render(<Skeleton />)

    const el = container.firstChild as HTMLElement
    expect(el.style.width).toBe('100%')
    expect(el.style.height).toBe('1em')
  })

  it('accepts a custom border radius, for a circular gauge placeholder', () => {
    const { container } = render(<Skeleton radius="50%" />)

    const el = container.firstChild as HTMLElement
    expect(el.style.borderRadius).toBe('50%')
  })
})
