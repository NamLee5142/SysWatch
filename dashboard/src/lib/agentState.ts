import type { AgentState } from '../api/types'

// One canonical label per state, shared by the app shell's header and the
// Overview page's own status tile, so the dashboard never describes the same
// fact two different ways depending which part of the screen you look at.
export const AGENT_STATE_LABEL: Record<AgentState, string> = {
  up: 'Connected',
  down: 'Agent unreachable',
  unknown: 'Unknown',
}
