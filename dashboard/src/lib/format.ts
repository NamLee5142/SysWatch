// A regular space between a number and its unit lets the browser wrap the
// line there, which orphans a lone "GB" on its own line in a narrow tile —
// this keeps the pair together as one unbreakable token.
const NBSP = ' '

/** Memory arrives from the backend in MB (see MemoryInfo in api/types.ts).
 *  Below 1 GB the raw MB count is more legible than "0.5 GB"; at or above it,
 *  GB reads faster than a four-to-six digit MB number. */
export function formatMemoryMB(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)}${NBSP}GB`
  }
  return `${Math.round(mb)}${NBSP}MB`
}

export function formatGB(gb: number): string {
  return `${Math.round(gb)}${NBSP}GB`
}

/** Network throughput from the backend (NetworkInterface.bytes*PerSec, and the
 *  net_sent / net_recv series). Steps through B/s, KB/s, MB/s, GB/s on 1024
 *  boundaries — the same binary convention formatMemoryMB uses, so the app is
 *  consistent with itself even though networking tools are split on 1000 vs
 *  1024. A negative rate (never sent by the agent, but cheap to guard) renders
 *  as 0. */
export function formatBytesPerSec(bytesPerSec: number): string {
  const value = bytesPerSec > 0 ? bytesPerSec : 0

  if (value < 1024) {
    return `${Math.round(value)}${NBSP}B/s`
  }

  const kb = value / 1024
  if (kb < 1024) {
    return `${kb.toFixed(1)}${NBSP}KB/s`
  }

  const mb = kb / 1024
  if (mb < 1024) {
    return `${mb.toFixed(1)}${NBSP}MB/s`
  }

  return `${(mb / 1024).toFixed(1)}${NBSP}GB/s`
}

/** A raw 0-100 number for feeding a Gauge, not a display string — the memory
 *  and disk pages' headline percentage, computed the same way the backend's
 *  own metric_expression() does it. Guarded against a zero or negative total
 *  the same way the backend guards its division: a bad collector reading
 *  must render as 0%, not NaN%. */
export function percentOf(part: number, total: number): number {
  if (total <= 0) {
    return 0
  }
  return (part / total) * 100
}

export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const thenMs = new Date(iso).getTime()
  // Not clamped to 0: every branch below is an upper bound starting from the
  // smallest, so a negative value (iso slightly ahead of now, e.g. clock skew
  // between the agent and the browser) already falls into "just now" the
  // same as zero would — clamping first would be a no-op, not a guard.
  const diffSeconds = Math.round((now.getTime() - thenMs) / 1000)

  if (diffSeconds < 5) {
    return 'just now'
  }
  if (diffSeconds < 60) {
    return `${diffSeconds}s ago`
  }

  const minutes = Math.floor(diffSeconds / 60)
  if (minutes < 60) {
    return `${minutes}m ago`
  }

  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }

  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
