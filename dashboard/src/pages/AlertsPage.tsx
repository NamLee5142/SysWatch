import type { ReactNode } from 'react'

import { getActiveAlerts, getAlerts, listAlertRules } from '../api/client'
import type { Alert, AlertRule, Severity } from '../api/types'
import { RelativeTime } from '../components/RelativeTime'
import { TableSkeletonRows } from '../components/TableSkeletonRows'
import { usePolling } from '../hooks/usePolling'
import { formatCondition, formatMetricValue, METRIC_LABEL, SEVERITY_LABEL } from '../lib/alerts'
import { POLL_INTERVAL_MS } from '../lib/constants'
import styles from './AlertsPage.module.css'

const RESOLVED_LIMIT = 20

const SEVERITY_CLASS: Record<Severity, string> = {
  info: styles.severityInfo,
  warning: styles.severityWarning,
  critical: styles.severityCritical,
}

const ALERT_HEADERS = ['Severity', 'Alert', 'Host', 'Value', 'Threshold', 'Since', 'State']
const RULE_HEADERS = ['Name', 'Metric', 'Condition', 'Severity', 'Enabled']

function alertRows(alerts: Alert[]): ReactNode {
  return alerts.map((alert) => (
    <tr key={alert.id}>
      <td className={`${styles.severity} ${SEVERITY_CLASS[alert.severity]}`}>
        {SEVERITY_LABEL[alert.severity]}
      </td>
      <td>{alert.ruleName}</td>
      <td>{alert.hostName}</td>
      <td>{formatMetricValue(alert.metric, alert.value)}</td>
      <td>{formatCondition(alert.metric, alert.operator, alert.threshold)}</td>
      <td>
        <RelativeTime iso={alert.triggeredAt} />
      </td>
      <td className={styles.state}>{alert.state === 'firing' ? 'Firing' : 'Resolved'}</td>
    </tr>
  ))
}

function ruleRows(rules: AlertRule[]): ReactNode {
  return rules.map((rule) => (
    <tr key={rule.id}>
      <td>{rule.name}</td>
      <td>{METRIC_LABEL[rule.metric]}</td>
      <td>{formatCondition(rule.metric, rule.operator, rule.threshold)}</td>
      <td className={`${styles.severity} ${SEVERITY_CLASS[rule.severity]}`}>
        {SEVERITY_LABEL[rule.severity]}
      </td>
      <td className={styles.state}>{rule.enabled ? 'Yes' : 'No'}</td>
    </tr>
  ))
}

interface TableSectionProps {
  title: string
  meta?: ReactNode
  headers: string[]
  loadingLabel: string
  errorText: string
  emptyText: string
  hasData: boolean
  isEmpty: boolean
  rows: ReactNode
  error: unknown
}

function TableSection({
  title,
  meta,
  headers,
  loadingLabel,
  errorText,
  emptyText,
  hasData,
  isEmpty,
  rows,
  error,
}: TableSectionProps) {
  const head = (
    <thead>
      <tr>
        {headers.map((header) => (
          <th key={header} scope="col">
            {header}
          </th>
        ))}
      </tr>
    </thead>
  )

  return (
    <section className={styles.section}>
      <h2>
        {title}
        {meta != null && <span className={styles.count}> {meta}</span>}
      </h2>

      {hasData ? (
        isEmpty ? (
          <p className={styles.placeholder}>{emptyText}</p>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              {head}
              <tbody>{rows}</tbody>
            </table>
          </div>
        )
      ) : error != null ? (
        <p className={styles.placeholder}>{errorText}</p>
      ) : (
        <div className={styles.tableWrapper} role="status">
          <span className="visually-hidden">{loadingLabel}</span>
          <table className={styles.table}>
            {head}
            <tbody>
              <TableSkeletonRows columns={headers.length} />
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function AlertsPage() {
  // Three independent polls, like SystemPage: the active list is the live one,
  // and the resolved list must refresh too so an alert that clears is seen to
  // move from one table to the other.
  const active = usePolling((signal) => getActiveAlerts(undefined, signal), POLL_INTERVAL_MS)
  const resolved = usePolling(
    (signal) => getAlerts({ state: 'ok', limit: RESOLVED_LIMIT }, signal),
    POLL_INTERVAL_MS,
  )
  const rules = usePolling(listAlertRules, POLL_INTERVAL_MS)

  return (
    <div className={styles.page}>
      <h1>Alerts</h1>

      <TableSection
        title="Active"
        meta={active.data ? active.data.items.length : undefined}
        headers={ALERT_HEADERS}
        loadingLabel="Loading active alerts"
        errorText="Unable to load active alerts."
        emptyText="No active alerts."
        hasData={Boolean(active.data)}
        isEmpty={active.data?.items.length === 0}
        rows={active.data ? alertRows(active.data.items) : null}
        error={active.error}
      />

      <TableSection
        title="Recently resolved"
        headers={ALERT_HEADERS}
        loadingLabel="Loading resolved alerts"
        errorText="Unable to load resolved alerts."
        emptyText="No resolved alerts yet."
        hasData={Boolean(resolved.data)}
        isEmpty={resolved.data?.items.length === 0}
        rows={resolved.data ? alertRows(resolved.data.items) : null}
        error={resolved.error}
      />

      <TableSection
        title="Rules"
        headers={RULE_HEADERS}
        loadingLabel="Loading alert rules"
        errorText="Unable to load alert rules."
        emptyText="No alert rules configured."
        hasData={Boolean(rules.data)}
        isEmpty={rules.data?.items.length === 0}
        rows={rules.data ? ruleRows(rules.data.items) : null}
        error={rules.error}
      />
    </div>
  )
}
