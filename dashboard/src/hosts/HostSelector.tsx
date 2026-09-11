import { useSelectedHost } from './SelectedHostContext'
import styles from './HostSelector.module.css'

/**
 * The machine being shown, and a way to change it.
 *
 * Renders as plain text until there is more than one host. A dropdown holding
 * a single option is a control that cannot do anything, and every
 * single-machine install - which is most of them - would have one in the
 * header forever.
 */
export function HostSelector() {
  const { hosts, hostName, loading, select } = useSelectedHost()

  if (hostName === null) {
    // No host has reported. Not an error: it is what a fresh install looks
    // like before the first collection, and the em dash is what the header
    // showed there before this existed.
    return <span className={styles.single}>{loading ? '' : '—'}</span>
  }

  if (hosts.length < 2) {
    return <span className={styles.single}>{hostName}</span>
  }

  return (
    <label className={styles.label}>
      <span className={styles.hidden}>Host</span>
      <select
        className={styles.select}
        value={hostName}
        onChange={(event) => select(event.target.value)}
      >
        {hosts.map((host) => (
          <option key={host.hostName} value={host.hostName}>
            {host.hostName}
          </option>
        ))}
      </select>
    </label>
  )
}
