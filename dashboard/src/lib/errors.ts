import { ApiError, NetworkError } from '../api/client'

/**
 * Maps a failed `/snapshots/latest` fetch to the message its cause actually
 * calls for, rather than one generic line for every failure:
 *
 * - NetworkError: the backend itself could not be reached at all.
 * - ApiError 404: the backend answered, there is simply nothing stored yet —
 *   the normal state on a fresh database, not a problem.
 * - anything else: an unexpected backend failure.
 *
 * These read very differently to someone looking at the screen, and only one
 * of them ("no data yet") is not actually bad news.
 */
export function describeSnapshotError(error: unknown): string {
  if (error instanceof NetworkError) {
    return "Can't reach the backend. Check that it's running."
  }
  if (error instanceof ApiError && error.status === 404) {
    return 'No data yet — waiting for the first snapshot.'
  }
  return 'Unable to load the latest snapshot.'
}
