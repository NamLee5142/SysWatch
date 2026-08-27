import { getLatestSnapshot, getStatus } from '../api/client'
import { GaugeCard } from '../components/GaugeCard'
import { RelativeTime } from '../components/RelativeTime'
import { StatCard } from '../components/StatCard'
import { StatusDot } from '../components/StatusDot'
import { usePolling } from '../hooks/usePolling'
import { AGENT_STATE_LABEL } from '../lib/agentState'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { formatGB, formatMemoryMB } from '../lib/format'
import styles from './OverviewPage.module.css'

export function OverviewPage() {
  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const status = usePolling(getStatus, POLL_INTERVAL_MS)

  const agentState = status.data?.agent ?? 'unknown'

  // Minimal on purpose: full loading skeletons and a three-way empty/error/
  // stale distinction are Phase E's job (commits 20-21). This just has to
  // not crash before that data exists, and say why in one line when it never
  // arrives.
  if (!snapshot.data) {
    return (
      <div className={styles.page}>
        <h1>Overview</h1>
        <p className={styles.placeholder}>
          {snapshot.error ? 'Unable to load the latest snapshot.' : 'Loading…'}
        </p>
      </div>
    )
  }

  const { cpuInfo, memoryInfo, diskInfo, systemInfo, collectedAt } = snapshot.data
  const diskUsedGB = diskInfo.totalGB - diskInfo.freeGB

  return (
    <div className={styles.page}>
      <h1>Overview</h1>
      <div className={styles.grid}>
        <GaugeCard value={cpuInfo.usagePercent} label="CPU" hint={`${cpuInfo.coreCount} cores`} />

        <StatCard
          label="Memory"
          value={`${formatMemoryMB(memoryInfo.usedMB)} / ${formatMemoryMB(memoryInfo.totalMB)}`}
          hint="used / total"
        />

        <StatCard label="Disk" value={`${formatGB(diskUsedGB)} used`} hint={`${formatGB(diskInfo.freeGB)} free`} />

        <StatCard label="Hostname" value={systemInfo.hostName} />

        <StatCard label="OS" value={`${systemInfo.name} ${systemInfo.version}`} />

        <StatCard label="Last update" value={<RelativeTime iso={collectedAt} />} />

        <StatCard
          label="Connection"
          value={
            <span className={styles.connectionValue}>
              <StatusDot state={agentState} />
              {AGENT_STATE_LABEL[agentState]}
            </span>
          }
        />
      </div>
    </div>
  )
}
