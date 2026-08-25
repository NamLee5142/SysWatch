import { NavLink, Outlet } from 'react-router-dom'

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
  { to: '/system', label: 'System' },
  { to: '/history', label: 'History' },
]

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink
}

export function AppShell() {
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
          {/* Static until the polling hooks land: this shell has to be
              reviewable on its own before it has anything live to show. */}
          <span className={styles.hostName}>—</span>
          <span className={styles.connection}>
            <span className={`${styles.dot} ${styles.dotUnknown}`} aria-hidden="true" />
            Unknown
          </span>
        </header>
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
