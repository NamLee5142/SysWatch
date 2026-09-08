import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, listSnapshots } from '../api/client'
import { renderWithHost } from '../test/renderWithHost'
import type { Snapshot, SnapshotPage } from '../api/types'
import { HistoryPage } from './HistoryPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listSnapshots: vi.fn(),
  }
})

function snapshotAt(minutesAgo: number, hostName = 'devbox'): Snapshot {
  return {
    collectedAt: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
    cpuInfo: { coreCount: 8, usagePercent: 42.5 },
    memoryInfo: { totalMB: 16384, usedMB: 4096 },
    diskInfo: { totalGB: 512, freeGB: 112 },
    systemInfo: { name: 'Windows', version: '11', hostName },
  }
}

function pageOf(items: Snapshot[], count = items.length): SnapshotPage {
  return { items, count }
}

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

beforeEach(() => {
  vi.mocked(listSnapshots).mockReset()
})

describe('HistoryPage', () => {
  it('shows a loading skeleton table before the first page arrives', () => {
    vi.mocked(listSnapshots).mockReturnValue(neverSettles())

    renderWithHost(<HistoryPage />)

    // The real column headers stay visible while the rows are still loading.
    const headers = screen.getAllByRole('columnheader')
    expect(headers).toHaveLength(5)
    expect(headers[0]).toHaveTextContent('Collected at')
    expect(screen.getByText('Loading history')).toBeInTheDocument()

    // The skeleton row itself matches the real table's column count — a
    // mismatch here would draw a skeleton with the wrong number of cells
    // under the five real headers.
    const skeletonRow = screen.getAllByRole('row')[1]
    expect(within(skeletonRow).getAllByRole('cell')).toHaveLength(5)
  })

  it('fetches page 0 for the selected host on mount', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)]))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))
    const [params] = vi.mocked(listSnapshots).mock.calls[0]
    expect(params).toMatchObject({ host: 'devbox', since: undefined, until: undefined, limit: 25, offset: 0 })
  })

  it('renders a row per snapshot with CPU, memory and disk', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0, 'devbox')]))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
    // No Host column: every row is the selected host, so it repeated the
    // header on every line.
    expect(screen.queryByRole('columnheader', { name: 'Host' })).not.toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '42.5%' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '4.0 GB / 16.0 GB' })).toBeInTheDocument()
    // 512 - 112 = 400 GB used.
    expect(screen.getByRole('cell', { name: '400 GB / 512 GB' })).toBeInTheDocument()
  })

  it('shows a specific empty message rather than a blank table', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([]))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByText('No snapshots match these filters.')).toBeInTheDocument())
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('has no host field of its own', async () => {
    // It had a free-text "Any host" box before the header had a selector.
    // Two controls for one idea is how they come to disagree, and the
    // interesting question then is which of them wins.
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)]))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))
    expect(screen.queryByLabelText('Host')).not.toBeInTheDocument()
  })

  it('queries whichever host is selected', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)]))

    renderWithHost(<HistoryPage />, { hostName: 'buildbox' })

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))
    expect(vi.mocked(listSnapshots).mock.calls[0][0]).toMatchObject({ host: 'buildbox' })
  })

  it('asks for nothing in particular when no host has reported', async () => {
    // A fresh install. Sending host=null would be a filter matching nothing;
    // omitting it returns whatever exists, which is nothing.
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([]))

    renderWithHost(<HistoryPage />, { hosts: [], hostName: null })

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))
    expect(vi.mocked(listSnapshots).mock.calls[0][0]).toMatchObject({ host: undefined })
  })

  it('converts the Since and Until filters to ISO strings before requesting', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)]))
    const user = userEvent.setup()

    renderWithHost(<HistoryPage />)
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))

    // <input type="datetime-local"> gives local wall-clock time with no
    // offset; the request must carry a real UTC ISO string, not that raw
    // value passed through untouched.
    await user.type(screen.getByLabelText('Since'), '2026-08-25T09:00')
    await user.type(screen.getByLabelText('Until'), '2026-08-25T17:00')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(2))
    const [params] = vi.mocked(listSnapshots).mock.calls[1]
    expect(params).toMatchObject({
      since: new Date('2026-08-25T09:00').toISOString(),
      until: new Date('2026-08-25T17:00').toISOString(),
    })
  })

  it('resets to page 0 when a new filter is submitted', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf(Array.from({ length: 25 }, (_, i) => snapshotAt(i)), 100))
    const user = userEvent.setup()

    renderWithHost(<HistoryPage />)
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(2))
    expect(vi.mocked(listSnapshots).mock.calls[1][0]).toMatchObject({ offset: 25 })

    await user.type(screen.getByLabelText('Since'), '2026-09-08T09:00')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(3))
    // Page 5 of the old query has no guaranteed meaning against the new one.
    expect(vi.mocked(listSnapshots).mock.calls[2][0]).toMatchObject({ offset: 0 })
    expect(vi.mocked(listSnapshots).mock.calls[2][0]?.since).toBeDefined()
  })

  it('clears filters and refetches page 0 unfiltered', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)]))
    const user = userEvent.setup()

    renderWithHost(<HistoryPage />)
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))

    await user.type(screen.getByLabelText('Since'), '2026-09-08T09:00')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(2))

    await user.click(screen.getByRole('button', { name: 'Clear' }))

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(3))
    // The host is not cleared with them: it is the header's, not this form's.
    expect(vi.mocked(listSnapshots).mock.calls[2][0]).toMatchObject({
      since: undefined,
      until: undefined,
      offset: 0,
      host: 'devbox',
    })
    expect(screen.getByLabelText('Since')).toHaveValue('')
  })

  it('disables Previous on the first page and Next when there is no more data', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)], 1))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('enables Next when more rows exist beyond the current page', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)], 100))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Next' })).not.toBeDisabled())
  })

  it('disables Next exactly at the last full page, not one page early or late', async () => {
    // count equals exactly one page size: offset (0) + PAGE_SIZE (25) === 25.
    // An off-by-one here (<= instead of <) would enable Next on a page that
    // has no further rows, and clicking it would return an empty page.
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)], 25))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled())
  })

  it('advances the offset by one page size when Next is clicked', async () => {
    vi.mocked(listSnapshots).mockResolvedValue(pageOf([snapshotAt(0)], 100))
    const user = userEvent.setup()

    renderWithHost(<HistoryPage />)
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(listSnapshots).toHaveBeenCalledTimes(2))
    expect(vi.mocked(listSnapshots).mock.calls[1][0]).toMatchObject({ offset: 25 })
  })

  it('shows the reversed-window 422 message inline rather than a generic error', async () => {
    vi.mocked(listSnapshots).mockRejectedValue(new ApiError(422, 'since must not be after until'))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByText('since must not be after until')).toBeInTheDocument())
    // The loading skeleton is for "hasn't tried yet", not "tried and failed"
    // — showing both at once would be a confusing, contradictory screen.
    expect(screen.queryByText('Loading history')).not.toBeInTheDocument()
  })

  it('shows a generic message for a non-422 failure', async () => {
    vi.mocked(listSnapshots).mockRejectedValue(new ApiError(503, 'ignored detail'))

    renderWithHost(<HistoryPage />)

    await waitFor(() => expect(screen.getByText('Unable to load history.')).toBeInTheDocument())
    expect(screen.queryByText('ignored detail')).not.toBeInTheDocument()
  })

  it('keeps the previous page visible alongside a new filter error, rather than clearing it', async () => {
    vi.mocked(listSnapshots).mockResolvedValueOnce(pageOf([snapshotAt(0, 'devbox')]))
    const user = userEvent.setup()

    renderWithHost(<HistoryPage />)
    await waitFor(() => expect(screen.getByRole('cell', { name: '42.5%' })).toBeInTheDocument())

    vi.mocked(listSnapshots).mockRejectedValueOnce(new ApiError(422, 'since must not be after until'))
    await user.type(screen.getByLabelText('Since'), '2026-08-25T12:00')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(screen.getByText('since must not be after until')).toBeInTheDocument())
    // The rows are still there under the error, not cleared by it.
    expect(screen.getByRole('cell', { name: '42.5%' })).toBeInTheDocument()
  })
})
