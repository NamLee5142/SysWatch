import { createContext, useContext } from 'react'

import type { Host } from '../api/types'

/**
 * Which machine the dashboard is showing.
 *
 * Every page was written when there was only ever one, so each fetched
 * "the latest snapshot" with no host and got whichever row was newest. With
 * two machines reporting that shows one of them, alternating, with nothing on
 * screen to say it is doing so.
 *
 * The selection lives here rather than in the URL. A route parameter would put
 * the host in every link and every test, and would mean nine routes growing a
 * segment for a choice that is really a preference: which machine am I looking
 * at today. It is persisted instead, so a reload lands where you left off.
 */
export interface SelectedHostValue {
  /** Every host that has ever reported, newest activity first. */
  hosts: Host[]
  /**
   * The chosen host, or null when none has reported yet.
   *
   * Null is a real state, not a loading placeholder: a fresh install with no
   * agent has no hosts, and pages must render that rather than wait forever.
   */
  hostName: string | null
  /** True until the first /hosts answer, so a selector can avoid flickering. */
  loading: boolean
  /**
   * When the selected host's most recent snapshot was collected, or null when
   * no host has reported.
   *
   * This is the only staleness signal that works for every host. /status
   * answers "can the backend reach the agent it polls", which is meaningful
   * for exactly one machine and says nothing about the ones that push.
   */
  lastCollectedAt: string | null
  select: (hostName: string) => void
}

export const SelectedHostContext = createContext<SelectedHostValue | null>(null)

export function useSelectedHost(): SelectedHostValue {
  const value = useContext(SelectedHostContext)

  if (value === null) {
    // A page reading this outside the provider would silently behave as though
    // no host were selected, which looks like "the agent is down" rather than
    // the wiring mistake it is.
    throw new Error('useSelectedHost must be used inside a SelectedHostProvider')
  }

  return value
}
