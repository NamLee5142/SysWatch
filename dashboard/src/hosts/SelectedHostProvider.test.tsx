import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHosts } from '../api/client'
import { POLL_INTERVAL_MS } from '../lib/constants'
import type { Host } from '../api/types'
import { useSelectedHost } from './SelectedHostContext'
import { SelectedHostProvider, STORAGE_KEY } from './SelectedHostProvider'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getHosts: vi.fn() }
})

function host(hostName: string): Host {
  return { hostName, lastCollectedAt: '2026-09-08T10:00:00Z', snapshotCount: 1 }
}

function Probe() {
  const { hostName, hosts, select } = useSelectedHost()
  return (
    <div>
      <p data-testid="selected">{hostName ?? 'none'}</p>
      <p data-testid="count">{hosts.length}</p>
      <button type="button" onClick={() => select('buildbox')}>
        choose buildbox
      </button>
    </div>
  )
}

function renderProvider() {
  return render(
    <SelectedHostProvider>
      <Probe />
    </SelectedHostProvider>,
  )
}

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(getHosts).mockReset()
})

describe('SelectedHostProvider', () => {
  it('selects the most recently active host when nothing is remembered', async () => {
    // /hosts comes back ordered by activity, so the first is the one most
    // likely to be worth looking at.
    vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox'), host('buildbox')] })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('devbox'))
  })

  it('has no host until one reports', async () => {
    vi.mocked(getHosts).mockResolvedValue({ items: [] })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('none'))
  })

  it('remembers the choice across a reload', async () => {
    vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox'), host('buildbox')] })
    const first = renderProvider()
    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('devbox'))

    await userEvent.click(screen.getByRole('button', { name: 'choose buildbox' }))
    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('buildbox'))

    // A reload is a fresh mount reading the same storage.
    first.unmount()
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('buildbox'))
  })

  it('falls back when the remembered host stops reporting', async () => {
    // Decommissioned, renamed, or its token revoked. Staying pinned to it
    // would show an empty dashboard that looks like an outage.
    window.localStorage.setItem(STORAGE_KEY, 'goneaway')
    vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox')] })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('devbox'))
  })

  it('does not jump back if the forgotten host returns', async () => {
    // The fallback moves the choice, not just the display. Otherwise a machine
    // coming back online would silently steal the view from the one being read.
    //
    // Asserted on what is shown rather than on storage: the fallback is
    // deliberately not written down, because a value that is not persisted is
    // re-derived the same way next time, and writing to localStorage while
    // rendering would make the provider impure for no gain.
    // Fake timers before the mount: usePolling creates its interval on mount,
    // and installing them afterwards leaves that interval on the real clock.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      window.localStorage.setItem(STORAGE_KEY, 'goneaway')
      vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox')] })

      renderProvider()
      await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('devbox'))

      // goneaway comes back on the next poll.
      vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox'), host('goneaway')] })
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 100)
      await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('2'))

      // The view stays where the fallback put it.
      expect(screen.getByTestId('selected')).toHaveTextContent('devbox')
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the selection when another host appears', async () => {
    vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox')] })
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))

    vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox'), host('buildbox')] })

    // The next poll adds it without moving the view.
    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('devbox'), {
      timeout: 200,
    })
  })

  it('survives storage that throws', async () => {
    // A private window, or a browser set to block site data. A dashboard that
    // will not render because it could not remember a preference is worse
    // than one that forgets.
    const getItem = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('blocked')
      })
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked')
      })
    vi.mocked(getHosts).mockResolvedValue({ items: [host('devbox')] })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('devbox'))

    getItem.mockRestore()
    setItem.mockRestore()
  })

  it('renders nothing broken while /hosts is failing', async () => {
    // The backend being unreachable must not take the whole shell down with
    // it; the staleness banner is what reports that.
    vi.mocked(getHosts).mockRejectedValue(new Error('offline'))

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('selected')).toHaveTextContent('none'))
  })
})
