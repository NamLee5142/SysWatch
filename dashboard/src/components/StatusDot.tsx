import type { AgentState } from '../api/types'
import styles from './StatusDot.module.css'

const DOT_CLASS: Record<AgentState, string> = {
  up: styles.dotUp,
  down: styles.dotDown,
  unknown: styles.dotUnknown,
}

interface StatusDotProps {
  state: AgentState
}

/** The small colored circle for agent/backend connectivity, shared by the
 *  app shell header and the Overview page's own connection tile so both
 *  read the same three states identically. */
export function StatusDot({ state }: StatusDotProps) {
  return <span className={`${styles.dot} ${DOT_CLASS[state]}`} aria-hidden="true" />
}
