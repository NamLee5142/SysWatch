import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { getHosts } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { SelectedHostContext, type SelectedHostValue } from './SelectedHostContext'

/**
 * Where the remembered choice is kept.
 *
 * localStorage rather than a cookie: nothing on the server needs to know which
 * machine somebody is looking at, and a cookie would send it on every request
 * for no reason. Per browser rather than per account is the right grain too -
 * it is a view preference, not a property of the user.
 */
export const STORAGE_KEY = 'syswatch.selectedHost'

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // Private windows, and browsers set to block site data, throw on access
    // rather than returning null. A dashboard that will not render because it
    // could not remember a preference is worse than one that forgets.
    return null
  }
}

function remember(hostName: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, hostName)
  } catch {
    // Same again: forgetting is acceptable, throwing is not.
  }
}

export function SelectedHostProvider({ children }: { children: ReactNode }) {
  // Polled, not fetched once: a second machine that starts reporting while the
  // dashboard is open should appear in the selector without a reload, which is
  // exactly when somebody is watching for it.
  const hostsState = usePolling(getHosts, POLL_INTERVAL_MS)
  const hosts = useMemo(() => hostsState.data?.items ?? [], [hostsState.data])

  const [chosen, setChosen] = useState<string | null>(remembered)

  const select = useCallback((hostName: string) => {
    setChosen(hostName)
    remember(hostName)
  }, [])

  // Adjusted during render rather than in an effect.
  //
  // The remembered name only counts while that host is still reporting: a
  // machine decommissioned, renamed, or whose token was revoked would leave
  // the dashboard pinned to a host with no data, looking like an outage. When
  // that happens the choice moves to the most recently active host - and it
  // has to *move*, not merely be overridden for display, or the old machine
  // coming back online would silently steal the view from the one being read.
  //
  // React's documented way to adjust state when inputs change is to set it
  // while rendering, which it handles by re-rendering before committing.
  // Doing it in an effect would paint the wrong host first and would be the
  // cascading update the linter warns about.
  const names = hosts.map((host) => host.hostName)
  const [seen, setSeen] = useState<string>('')
  // JSON rather than a join: a host name is whatever an operator called
  // the token, so no separator character is safe to assume absent.
  const fingerprint = JSON.stringify(names)

  if (fingerprint !== seen) {
    setSeen(fingerprint)
    if (names.length > 0 && chosen !== null && !names.includes(chosen)) {
      setChosen(names[0])
    }
  }

  // Not persisted here. A fallback that is not written down is re-derived the
  // same way on the next load, and writing to localStorage while rendering
  // would make this function impure for no gain.
  const hostName = useMemo(() => {
    if (hosts.length === 0) {
      return null
    }
    if (chosen !== null && names.includes(chosen)) {
      return chosen
    }
    return names[0]
  }, [hosts, chosen, names])

  const lastCollectedAt =
    hosts.find((host) => host.hostName === hostName)?.lastCollectedAt ?? null

  const value: SelectedHostValue = useMemo(
    () => ({
      hosts,
      hostName,
      loading: hostsState.loading && hostsState.data === null,
      lastCollectedAt,
      select,
    }),
    [hosts, hostName, hostsState.loading, hostsState.data, lastCollectedAt, select],
  )

  return (
    <SelectedHostContext.Provider value={value}>{children}</SelectedHostContext.Provider>
  )
}
