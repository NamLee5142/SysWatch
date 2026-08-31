import { describe, expect, it } from 'vitest'

import { ApiError, NetworkError } from '../api/client'
import { describeSnapshotError } from './errors'

describe('describeSnapshotError', () => {
  it('describes a NetworkError as the backend being unreachable', () => {
    expect(describeSnapshotError(new NetworkError(new TypeError('Failed to fetch')))).toBe(
      "Can't reach the backend. Check that it's running.",
    )
  })

  it('describes a 404 as the normal, expected state on a fresh database', () => {
    expect(describeSnapshotError(new ApiError(404, 'No snapshot stored yet'))).toBe(
      'No data yet — waiting for the first snapshot.',
    )
  })

  it('falls back to a generic message for a 404 look-alike that is not actually one', () => {
    // A 500 is a real failure, not "nothing stored yet" — conflating the two
    // would tell someone to wait for data that a broken backend will never
    // produce.
    expect(describeSnapshotError(new ApiError(500, 'Internal Server Error'))).toBe(
      'Unable to load the latest snapshot.',
    )
  })

  it('falls back to a generic message for a value that is not one of these error types at all', () => {
    expect(describeSnapshotError(new Error('something unrelated'))).toBe('Unable to load the latest snapshot.')
    expect(describeSnapshotError('a plain string')).toBe('Unable to load the latest snapshot.')
    expect(describeSnapshotError(undefined)).toBe('Unable to load the latest snapshot.')
  })
})
