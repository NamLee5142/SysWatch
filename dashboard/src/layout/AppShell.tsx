import { NavLink, Outlet } from 'react-router-dom'

import { getLatestSnapshot, getStatus } from '../api/client'
import { StalenessBanner } from '../components/StalenessBanner'
import { StatusDot } from '../components/StatusDot'
import { usePolling } from '../hooks/usePolling'
import { AGENT_STATE_LABEL } from '../lib/agentState'
import { POLL_INTERVAL_MS } from '../lib/constants'
import styles from './AppShell.module.css'

interface NavItem {
  to: string
  label: string
  // Kept on the root link as the documented, version-independent way to pin
  // an index NavLink to its own route. Verified this react-router release
  // already treats "/" as an exact match on its own (its boundary check on
  // the resolved path rules out "/" prefix-matching "/history"), so this is
  // defensive rather than currently load-bearing — cheap insurance if that
  // internal behaviour, or the route itself, ever changes.
  end?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Overview', end: true },
  { to: '/cpu', label: 'CPU' },
  { to: '/memory', label: 'Memory' },
  { to: '/disk', label: 'Disk' },
  { to: '/processes', label: 'Processes' },
  { to: '/network', label: 'Network' },
  { to: '/system', label: 'System' },
  { to: '/history', label: 'History' },
  { to: '/alerts', label: 'Alerts' },
]

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink
}

export function AppShell() {
  // Independent of whatever the current page fetches: this header is chrome
  // rendered on every route, including ones (History, System) that do not
  // themselves poll the latest snapshot. A little duplicated polling against
  // a cheap SQLite read is the cost of that — see the "Data fetching" locked
  // decision for why this app has no shared request cache to avoid it.
  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const status = usePolling(getStatus, POLL_INTERVAL_MS)

  const agentState = status.data?.agent ?? 'unknown'
  const hostName = snapshot.data?.systemInfo.hostName

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <p className={styles.brand}>SysWatch</p>
        <nav aria-label="Sections">
          <ul className={styles.nav}>
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end} className={navLinkClassName}>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <div className={styles.main}>
        <header className={styles.header}>
          <span className={styles.hostName}>{hostName ?? '—'}</span>
          <span className={styles.connection}>
            <StatusDot state={agentState} />
            {AGENT_STATE_LABEL[agentState]}
          </span>
        </header>
        <StalenessBanner agentState={agentState} />
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
