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


/**
 * Maps a failed login to what the person at the keyboard should do next.
 *
 * The backend answers every bad-credential case identically on purpose — it
 * will not say whether the username exists — so this must not invent a
 * distinction either. What it does add is the rate limit's countdown, which is
 * actionable in a way "try again later" is not.
 */
export function describeLoginError(error: unknown): string {
  if (error instanceof NetworkError) {
    return "Can't reach the backend. Check that it's running."
  }

  if (error instanceof ApiError) {
    if (error.status === 429) {
      const seconds = error.retryAfter
      return seconds === undefined
        ? 'Too many failed attempts. Try again shortly.'
        : `Too many failed attempts. Try again in ${seconds} seconds.`
    }

    if (error.status === 401) {
      return 'Invalid username or password.'
    }

    return error.message
  }

  return 'Something went wrong signing in.'
}


/**
 * Maps a failed alert-rule change to something the person can act on.
 *
 * The 403 case is the one that matters: the dashboard hides these controls
 * from a viewer, but hiding is not what stops them — the backend refuses
 * regardless. Anyone who reaches this message has got past the hiding, and
 * telling them why is better than a generic failure.
 */
export function describeRuleError(error: unknown): string {
  if (error instanceof NetworkError) {
    return "Can't reach the backend. Check that it's running."
  }

  if (error instanceof ApiError) {
    if (error.status === 403) {
      return 'Only an admin can change alert rules.'
    }
    if (error.status === 404) {
      return 'That rule no longer exists.'
    }
    return error.message
  }

  return 'Unable to save the change.'
}
