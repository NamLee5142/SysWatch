import { useState, type FormEvent } from 'react'

import type { AlertRuleInput } from '../api/client'
import type { Metric, Operator, Severity } from '../api/types'
import { METRIC_LABEL, OPERATOR_SYMBOL } from '../lib/alerts'
import styles from './AlertsPage.module.css'

const METRICS: Metric[] = ['cpu', 'memory', 'disk', 'processes', 'net_sent', 'net_recv']
const OPERATORS: Operator[] = ['gt', 'gte', 'lt', 'lte']
const SEVERITIES: Severity[] = ['info', 'warning', 'critical']

interface AlertRuleFormProps {
  onSubmit: (rule: AlertRuleInput) => Promise<void>
  onCancel: () => void
  busy: boolean
}

export function AlertRuleForm({ onSubmit, onCancel, busy }: AlertRuleFormProps) {
  const [name, setName] = useState('')
  const [metric, setMetric] = useState<Metric>('cpu')
  const [operator, setOperator] = useState<Operator>('gt')
  const [threshold, setThreshold] = useState('90')
  const [severity, setSeverity] = useState<Severity>('warning')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void onSubmit({ name: name.trim(), metric, operator, threshold: Number(threshold), severity })
  }

  return (
    <form className={styles.ruleForm} onSubmit={handleSubmit}>
      <label className={styles.field}>
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} required />
      </label>

      <label className={styles.field}>
        <span>Metric</span>
        <select value={metric} onChange={(event) => setMetric(event.target.value as Metric)}>
          {METRICS.map((option) => (
            <option key={option} value={option}>
              {METRIC_LABEL[option]}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.field}>
        <span>Operator</span>
        <select value={operator} onChange={(event) => setOperator(event.target.value as Operator)}>
          {OPERATORS.map((option) => (
            <option key={option} value={option}>
              {OPERATOR_SYMBOL[option]}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.field}>
        <span>Threshold</span>
        {/* The unit depends on the metric — percent, a count, bytes per second
            — so this stays a bare number rather than pretending to know. */}
        <input
          type="number"
          step="any"
          value={threshold}
          onChange={(event) => setThreshold(event.target.value)}
          required
        />
      </label>

      <label className={styles.field}>
        <span>Severity</span>
        <select value={severity} onChange={(event) => setSeverity(event.target.value as Severity)}>
          {SEVERITIES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>

      <div className={styles.formActions}>
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Create rule'}
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
