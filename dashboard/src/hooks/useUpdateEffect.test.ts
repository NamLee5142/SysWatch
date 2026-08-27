import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useUpdateEffect } from './useUpdateEffect'

describe('useUpdateEffect', () => {
  it('does not run on mount', () => {
    const effect = vi.fn()

    renderHook(() => useUpdateEffect(effect, [1]))

    expect(effect).not.toHaveBeenCalled()
  })

  it('runs when a dependency changes', () => {
    const effect = vi.fn()

    const { rerender } = renderHook(({ dep }) => useUpdateEffect(effect, [dep]), {
      initialProps: { dep: 1 },
    })
    expect(effect).not.toHaveBeenCalled()

    rerender({ dep: 2 })

    expect(effect).toHaveBeenCalledTimes(1)
  })

  it('does not run again on a re-render where the dependency is unchanged', () => {
    const effect = vi.fn()

    const { rerender } = renderHook(({ dep }) => useUpdateEffect(effect, [dep]), {
      initialProps: { dep: 1 },
    })

    rerender({ dep: 1 })

    expect(effect).not.toHaveBeenCalled()
  })

  it('runs once per subsequent change, not cumulatively', () => {
    const effect = vi.fn()

    const { rerender } = renderHook(({ dep }) => useUpdateEffect(effect, [dep]), {
      initialProps: { dep: 1 },
    })

    rerender({ dep: 2 })
    rerender({ dep: 3 })
    rerender({ dep: 4 })

    expect(effect).toHaveBeenCalledTimes(3)
  })

  it('calls the latest effect closure, not the one captured on mount', () => {
    let observed = ''
    const { rerender } = renderHook(
      ({ dep, value }) => useUpdateEffect(() => { observed = value }, [dep]),
      { initialProps: { dep: 1, value: 'first' } },
    )

    rerender({ dep: 2, value: 'second' })

    expect(observed).toBe('second')
  })
})
