import { useState, type FormEvent } from 'react'

import { ApiError, listSnapshots } from '../api/client'
import { TableSkeletonRows } from '../components/TableSkeletonRows'
import { useSelectedHost } from '../hosts/SelectedHostContext'
import { useApi } from '../hooks/useApi'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { formatGB, formatMemoryMB } from '../lib/format'
import styles from './HistoryPage.module.css'

const PAGE_SIZE = 25

interface Filters {
  // Raw <input type="datetime-local"> values (local wall-clock time, no
  // offset), or '' when unset. Converted to UTC ISO only at request time.
  since: string
  until: string
}

const EMPTY_FILTERS: Filters = { since: '', until: '' }

function toIso(localValue: string): string | undefined {
  return localValue ? new Date(localValue).toISOString() : undefined
}

export function HistoryPage() {
  // The host comes from the header, not from a field of its own. This page had
  // a free-text "Any host" box before there was a selector; keeping both would
  // be two controls for one idea, and the interesting question is which of them
  // wins when they disagree.
  const { hostName } = useSelectedHost()
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS)
  const [page, setPage] = useState(0)

  const history = useApi((signal) =>
    listSnapshots(
      {
        host: hostName ?? undefined,
        since: toIso(applied.since),
        until: toIso(applied.until),
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      },
      signal,
    ),
  )

  // Not usePolling: this is a query interface, not a live tile. Overwriting
  // the table out from under someone mid-read every 5 seconds is worse than
  // requiring them to re-search — refetch on filter or page change only.
  useUpdateEffect(() => {
    history.refetch()
  }, [applied, page, history.refetch])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    // A new filter set starts its own page sequence — page 5 of the old
    // query has no guaranteed meaning against the new one.
    setPage(0)
    setApplied(draft)
  }

  function handleClear() {
    setDraft(EMPTY_FILTERS)
    setPage(0)
    setApplied(EMPTY_FILTERS)
  }

  const count = history.data?.count ?? 0
  const offset = page * PAGE_SIZE
  const hasPreviousPage = page > 0
  const hasNextPage = offset + PAGE_SIZE < count

  // The backend's own validation (_validate_window) answers a bad range with
  // a 422 carrying a plain-English detail string — surfaced verbatim instead
  // of behind a generic "something went wrong".
  const is422 = history.error instanceof ApiError && history.error.status === 422

  return (
    <div className={styles.page}>
      <h1>History</h1>

      <form className={styles.filters} onSubmit={handleSubmit}>
        <label className={styles.field}>
          <span>Since</span>
          <input
            type="datetime-local"
            value={draft.since}
            onChange={(event) => setDraft({ ...draft, since: event.target.value })}
          />
        </label>
        <label className={styles.field}>
          <span>Until</span>
          <input
            type="datetime-local"
            value={draft.until}
            onChange={(event) => setDraft({ ...draft, until: event.target.value })}
          />
        </label>
        <div className={styles.actions}>
          <button type="submit">Search</button>
          <button type="button" onClick={handleClear}>
            Clear
          </button>
        </div>
      </form>

      {Boolean(history.error) && (
        <p className={styles.filterError}>
          {is422 ? (history.error as ApiError).message : 'Unable to load history.'}
        </p>
      )}

      {!history.data && !history.error && (
        <div className={styles.tableWrapper} role="status">
          <span className="visually-hidden">Loading history</span>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Collected at</th>
                <th scope="col">Host</th>
                <th scope="col">CPU</th>
                <th scope="col">Memory</th>
                <th scope="col">Disk</th>
              </tr>
            </thead>
            <tbody>
              <TableSkeletonRows columns={5} />
            </tbody>
          </table>
        </div>
      )}

      {history.data &&
        (history.data.items.length === 0 ? (
          <p className={styles.placeholder}>No snapshots match these filters.</p>
        ) : (
          <>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Collected at</th>
                    <th scope="col">CPU</th>
                    <th scope="col">Memory</th>
                    <th scope="col">Disk</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.items.map((item, index) => (
                    <tr key={`${item.systemInfo.hostName}-${item.collectedAt}-${index}`}>
                      <td>{new Date(item.collectedAt).toLocaleString()}</td>
                      <td>{`${item.cpuInfo.usagePercent.toFixed(1)}%`}</td>
                      <td>{`${formatMemoryMB(item.memoryInfo.usedMB)} / ${formatMemoryMB(item.memoryInfo.totalMB)}`}</td>
                      <td>
                        {`${formatGB(item.diskInfo.totalGB - item.diskInfo.freeGB)} / ${formatGB(item.diskInfo.totalGB)}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.pagination}>
              <span>
                {count === 0 ? '0 results' : `${offset + 1}–${Math.min(offset + PAGE_SIZE, count)} of ${count}`}
              </span>
              <div className={styles.pageButtons}>
                <button type="button" onClick={() => setPage((current) => current - 1)} disabled={!hasPreviousPage}>
                  Previous
                </button>
                <button type="button" onClick={() => setPage((current) => current + 1)} disabled={!hasNextPage}>
                  Next
                </button>
              </div>
            </div>
          </>
        ))}
    </div>
  )
}
