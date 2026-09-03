import { useState, type ReactNode } from 'react'

import {
  createAlertRule,
  deleteAlertRule,
  getActiveAlerts,
  getAlerts,
  listAlertRules,
  updateAlertRule,
  type AlertRuleInput,
} from '../api/client'
import type { Alert, AlertRule, Severity } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { RelativeTime } from '../components/RelativeTime'
import { TableSkeletonRows } from '../components/TableSkeletonRows'
import { usePolling } from '../hooks/usePolling'
import { formatCondition, formatMetricValue, METRIC_LABEL, SEVERITY_LABEL } from '../lib/alerts'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { describeRuleError } from '../lib/errors'
import { AlertRuleForm } from './AlertRuleForm'
import styles from './AlertsPage.module.css'

const RESOLVED_LIMIT = 20

const SEVERITY_CLASS: Record<Severity, string> = {
  info: styles.severityInfo,
  warning: styles.severityWarning,
  critical: styles.severityCritical,
}

const ALERT_HEADERS = ['Severity', 'Alert', 'Host', 'Value', 'Threshold', 'Since', 'State']
const RULE_HEADERS = ['Name', 'Metric', 'Condition', 'Severity', 'Enabled']
const ADMIN_RULE_HEADERS = [...RULE_HEADERS, 'Actions']

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

interface RuleActions {
  isAdmin: boolean
  busyId: number | null
  onToggle: (rule: AlertRule) => void
  onDelete: (rule: AlertRule) => void
}

function ruleRows(rules: AlertRule[], actions: RuleActions): ReactNode {
  return rules.map((rule) => (
    <tr key={rule.id}>
      <td>{rule.name}</td>
      <td>{METRIC_LABEL[rule.metric]}</td>
      <td>{formatCondition(rule.metric, rule.operator, rule.threshold)}</td>
      <td className={`${styles.severity} ${SEVERITY_CLASS[rule.severity]}`}>
        {SEVERITY_LABEL[rule.severity]}
      </td>
      <td className={styles.state}>{rule.enabled ? 'Yes' : 'No'}</td>
      {actions.isAdmin && (
        <td>
          <span className={styles.rowActions}>
            <button
              type="button"
              onClick={() => actions.onToggle(rule)}
              disabled={actions.busyId === rule.id}
            >
              {rule.enabled ? 'Disable' : 'Enable'}
            </button>
            <button
              type="button"
              className={styles.danger}
              onClick={() => actions.onDelete(rule)}
              disabled={actions.busyId === rule.id}
            >
              Delete
            </button>
          </span>
        </td>
      )}
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
  /** Controls belonging to the section, shown beside its heading. */
  action?: ReactNode
  /** Rendered under the heading — a form, or the message from a failed write. */
  banner?: ReactNode
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
  action,
  banner,
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
      <div className={styles.sectionHeader}>
        <h2>
          {title}
          {meta != null && <span className={styles.count}> {meta}</span>}
        </h2>
        {action}
      </div>

      {banner}

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
  const { isAdmin } = useAuth()

  // Three independent polls, like SystemPage: the active list is the live one,
  // and the resolved list must refresh too so an alert that clears is seen to
  // move from one table to the other.
  const active = usePolling((signal) => getActiveAlerts(undefined, signal), POLL_INTERVAL_MS)
  const resolved = usePolling(
    (signal) => getAlerts({ state: 'ok', limit: RESOLVED_LIMIT }, signal),
    POLL_INTERVAL_MS,
  )
  const rules = usePolling(listAlertRules, POLL_INTERVAL_MS)

  const [adding, setAdding] = useState(false)
  // busyId disables the row being changed; saving covers the create form, which
  // has no row to point at.
  const [busyId, setBusyId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [ruleError, setRuleError] = useState<string | null>(null)

  // Every mutation runs through here so the refetch, the busy flag and the
  // error message cannot get out of step with each other.
  async function mutate(id: number | null, change: () => Promise<unknown>) {
    setRuleError(null)
    setBusyId(id)
    setSaving(true)

    try {
      await change()
      // The list is polled, but waiting up to five seconds to see your own
      // click take effect reads as the click not having worked.
      await rules.refetch()
      return true
    } catch (cause) {
      setRuleError(describeRuleError(cause))
      return false
    } finally {
      setBusyId(null)
      setSaving(false)
    }
  }

  async function handleCreate(rule: AlertRuleInput) {
    if (await mutate(null, () => createAlertRule(rule))) {
      setAdding(false)
    }
  }

  function handleToggle(rule: AlertRule) {
    void mutate(rule.id, () => updateAlertRule(rule.id, { enabled: !rule.enabled }))
  }

  function handleDelete(rule: AlertRule) {
    // Deleting a rule also orphans its alert history, so this asks first.
    if (!window.confirm(`Delete the rule "${rule.name}"?`)) {
      return
    }
    void mutate(rule.id, () => deleteAlertRule(rule.id))
  }

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
        headers={isAdmin ? ADMIN_RULE_HEADERS : RULE_HEADERS}
        loadingLabel="Loading alert rules"
        errorText="Unable to load alert rules."
        emptyText="No alert rules configured."
        hasData={Boolean(rules.data)}
        isEmpty={rules.data?.items.length === 0}
        rows={
          rules.data
            ? ruleRows(rules.data.items, {
                isAdmin,
                busyId,
                onToggle: handleToggle,
                onDelete: handleDelete,
              })
            : null
        }
        error={rules.error}
        action={
          // Hidden from a viewer as a courtesy. What actually stops them is
          // require_admin on the backend, which refuses these calls however
          // they are made.
          isAdmin && !adding ? (
            <button type="button" className={styles.toggle} onClick={() => setAdding(true)}>
              Add rule
            </button>
          ) : null
        }
        banner={
          <>
            {isAdmin && adding && (
              <AlertRuleForm
                onSubmit={handleCreate}
                onCancel={() => {
                  setAdding(false)
                  setRuleError(null)
                }}
                busy={saving}
              />
            )}
            {ruleError !== null && (
              <p className={styles.ruleError} role="alert">
                {ruleError}
              </p>
            )}
          </>
        }
      />
    </div>
  )
}
