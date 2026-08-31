import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useApi } from './useApi'

/** A promise this test controls the resolution of, to sequence two
 *  in-flight fetches deliberately rather than racing real ones. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** One turn of the event loop: enough for a microtask-queued .then() to run
 *  and, wrapped in act(), for the resulting render to commit. A bare await
 *  on a resolved promise is not sufficient here: an update triggered outside
 *  an event handler does not always commit within the same microtask
 *  checkpoint, so a fixed single tick can observe stale state and miss a
 *  real bug (see the comment on the stale-response test below). */
function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

describe('useApi', () => {
  it('starts loading with no data', () => {
    const { result } = renderHook(() => useApi(() => new Promise<string>(() => {})))

    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBeUndefined()
  })

  it('fetches once on mount and exposes the result', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')

    const { result } = renderHook(() => useApi(fetcher))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toBe('ok')
    expect(result.current.error).toBeUndefined()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('surfaces a rejection as error and stops loading', async () => {
    const failure = new Error('boom')
    const fetcher = vi.fn().mockRejectedValue(failure)

    const { result } = renderHook(() => useApi(fetcher))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBe(failure)
    expect(result.current.data).toBeUndefined()
  })

  it('keeps the previous data visible while a refetch is in flight', async () => {
    const first = deferred<string>()
    const second = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const { result } = renderHook(() => useApi(fetcher))

    act(() => first.resolve('first'))
    await waitFor(() => expect(result.current.data).toBe('first'))

    act(() => result.current.refetch())

    // The second fetch is in flight and unresolved: loading is true again,
    // but the page still has something to show.
    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBe('first')

    act(() => second.resolve('second'))
    await waitFor(() => expect(result.current.data).toBe('second'))
  })

  it('clears a previous error once a refetch succeeds', async () => {
    const failure = new Error('boom')
    const fetcher = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce('recovered')

    const { result } = renderHook(() => useApi(fetcher))

    await waitFor(() => expect(result.current.error).toBe(failure))

    act(() => result.current.refetch())

    await waitFor(() => expect(result.current.data).toBe('recovered'))
    expect(result.current.error).toBeUndefined()
  })

  it('ignores a stale success that resolves after a newer refetch', async () => {
    const stale = deferred<string>()
    const fresh = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise)

    const { result } = renderHook(() => useApi(fetcher))

    // Refetch before the first request has resolved at all: the component
    // now only cares about the second request's answer.
    act(() => result.current.refetch())

    await act(async () => {
      fresh.resolve('fresh')
      await flush()
    })
    expect(result.current.data).toBe('fresh')

    // The stale first request finally resolves. Its result must not clobber
    // the fresher one that already landed. This checks with the same
    // act()+flush() as above rather than a single bare await: a fixed one
    // tick delay is not reliably enough time for the (buggy) unguarded
    // update to commit either, so a test written that way can pass even
    // when this guard is missing.
    await act(async () => {
      stale.resolve('stale')
      await flush()
    })
    expect(result.current.data).toBe('fresh')
  })

  it('ignores a stale rejection that arrives after a newer successful refetch', async () => {
    const stale = deferred<string>()
    const fresh = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise)

    const { result } = renderHook(() => useApi(fetcher))

    act(() => result.current.refetch())

    await act(async () => {
      fresh.resolve('fresh')
      await flush()
    })
    expect(result.current.data).toBe('fresh')

    // The superseded request fails instead of resolving. That failure must
    // not retroactively turn a page that is successfully showing data into
    // an error page.
    await act(async () => {
      stale.reject(new Error('stale failure'))
      await flush()
    })
    expect(result.current.data).toBe('fresh')
    expect(result.current.error).toBeUndefined()
  })

  it('aborts the in-flight request when superseded by a refetch', () => {
    const signals: AbortSignal[] = []
    const fetcher = vi.fn((signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<string>(() => {})
    })

    const { result } = renderHook(() => useApi(fetcher))
    expect(signals).toHaveLength(1)
    expect(signals[0].aborted).toBe(false)

    act(() => result.current.refetch())

    expect(signals[0].aborted).toBe(true)
    expect(signals).toHaveLength(2)
    expect(signals[1].aborted).toBe(false)
  })

  it('aborts the in-flight request on unmount', () => {
    const signals: AbortSignal[] = []
    const fetcher = vi.fn((signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<string>(() => {})
    })

    const { unmount } = renderHook(() => useApi(fetcher))
    unmount()

    expect(signals[0].aborted).toBe(true)
  })

  it('does not update state when the fetch settles after unmounting', async () => {
    // AbortController is jsdom's native implementation here, not a mock, so
    // this exercises the real event: unmount aborts the signal, the fetcher
    // reacts to that exactly as a real one built on fetch() would, and the
    // hook must not act on what comes back.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const fetcher = vi.fn(
      (signal: AbortSignal) =>
        new Promise<string>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        }),
    )

    const { unmount } = renderHook(() => useApi(fetcher))
    unmount()

    await flush()

    // React logs to console.error when a state setter fires after unmount;
    // its absence is the observable proof that nothing tried to.
    expect(consoleError).not.toHaveBeenCalled()
    consoleError.mockRestore()
  })

  it('refetches when refetch is called', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { result } = renderHook(() => useApi(fetcher))

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    act(() => result.current.refetch())

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  })

  it('always calls the latest fetcher, not the one captured at mount', async () => {
    const fetcherA = vi.fn().mockResolvedValue('a')
    const fetcherB = vi.fn().mockResolvedValue('b')

    const { result, rerender } = renderHook(({ fetcher }) => useApi(fetcher), {
      initialProps: { fetcher: fetcherA },
    })
    await waitFor(() => expect(result.current.data).toBe('a'))

    // A new fetcher identity, the way an inline arrow function passed by a
    // component would look after any re-render — refetch() must pick this
    // one up rather than the one closed over when the effect first ran.
    rerender({ fetcher: fetcherB })
    act(() => result.current.refetch())

    await waitFor(() => expect(result.current.data).toBe('b'))
    expect(fetcherA).toHaveBeenCalledTimes(1)
    expect(fetcherB).toHaveBeenCalledTimes(1)
  })
})
