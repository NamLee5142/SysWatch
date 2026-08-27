import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RelativeTime } from './RelativeTime'

const NOW = new Date('2026-08-25T12:00:00Z')

function secondsAgo(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString()
}

describe('RelativeTime', () => {
  beforeEach(() => {
    // No shouldAdvanceTime here: nothing in this block uses waitFor or waits
    // on real I/O, so there is no deadlock risk to trade against — and
    // combining it with an explicit vi.setSystemTime() call double-counts
    // elapsed time (real drift on top of the manual jump), which is exactly
    // what made this test's first version report the wrong age.
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the formatted age on mount', () => {
    render(<RelativeTime iso={secondsAgo(10)} />)

    expect(screen.getByText('10s ago')).toBeInTheDocument()
  })

  it('counts up on its own, without new data arriving', () => {
    // This is the entire point of the component: a stale dashboard must not
    // look frozen just because the underlying `iso` value stopped changing.
    render(<RelativeTime iso={secondsAgo(10)} />)
    expect(screen.getByText('10s ago')).toBeInTheDocument()

    // Advancing the fake clock advances Date.now()/`new Date()` along with
    // it, so this alone moves both "now" and the elapsed interval ticks —
    // no separate setSystemTime call needed.
    act(() => {
      vi.advanceTimersByTime(5000)
    })

    expect(screen.getByText('15s ago')).toBeInTheDocument()
  })

  it('exposes the raw timestamp via dateTime for assistive tech and tooling', () => {
    const iso = secondsAgo(10)
    render(<RelativeTime iso={iso} />)

    expect(screen.getByText('10s ago').closest('time')).toHaveAttribute('dateTime', iso)
  })

  it('stops ticking after unmount', async () => {
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')
    const { unmount } = render(<RelativeTime iso={secondsAgo(10)} />)

    unmount()

    expect(clearIntervalSpy).toHaveBeenCalled()
  })
})
