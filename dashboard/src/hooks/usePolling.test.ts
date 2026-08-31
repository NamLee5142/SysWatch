import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePolling } from './usePolling'

function setDocumentHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
    setDocumentHidden(false)
  })

  it('fetches once on mount', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')

    renderHook(() => usePolling(fetcher, 5000))

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  })

  it('fetches again after the interval elapses', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(fetcher, 5000))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('does not poll while the tab is hidden', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(fetcher, 5000))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    setDocumentHidden(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    // Still just the initial mount fetch: two ticks passed while hidden.
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('resumes polling once the tab is hidden and a tick passes', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(fetcher, 5000))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    setDocumentHidden(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    setDocumentHidden(false)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('refetches immediately when the tab becomes visible again', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(fetcher, 5000))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    setDocumentHidden(true)
    document.dispatchEvent(new Event('visibilitychange'))
    // Still hidden: the listener itself checks document.hidden and must not
    // fire on the transition into hidden.
    expect(fetcher).toHaveBeenCalledTimes(1)

    setDocumentHidden(false)
    document.dispatchEvent(new Event('visibilitychange'))

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  })

  it('stops polling on unmount', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { unmount } = renderHook(() => usePolling(fetcher, 5000))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000)
    })

    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('clears the underlying interval on unmount', async () => {
    // The assertion above (no further fetches) does not actually prove the
    // interval was cleared: React 18 silently no-ops a state update from an
    // unmounted component, so a leaked interval calling refetch() forever
    // would be invisible through fetch-count alone. This checks the cleanup
    // mechanism directly instead of inferring it from that masked side effect.
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { unmount } = renderHook(() => usePolling(fetcher, 5000))
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    unmount()

    expect(clearIntervalSpy).toHaveBeenCalled()
  })

  it('restarts the interval when intervalMs changes', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { rerender } = renderHook(({ interval }) => usePolling(fetcher, interval), {
      initialProps: { interval: 5000 },
    })
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    rerender({ interval: 1000 })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('exposes the same data/error/loading/refetch shape as useApi', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { result } = renderHook(() => usePolling(fetcher, 5000))

    await waitFor(() => expect(result.current.data).toBe('ok'))
    expect(result.current.error).toBeUndefined()
    expect(typeof result.current.refetch).toBe('function')
  })
})
