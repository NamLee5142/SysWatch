import type { ReactNode } from 'react'

import styles from './StatCard.module.css'

interface StatCardProps {
  label: string
  value: ReactNode
  hint?: ReactNode
}

/** A single labeled value — the headline number on Overview and each metric
 *  page (CPU %, memory used, disk free, ...). */
export function StatCard({ label, value, hint }: StatCardProps) {
  return (
    <div className={styles.card}>
      <p className={styles.label}>{label}</p>
      <p className={styles.value}>{value}</p>
      {hint !== undefined && <p className={styles.hint}>{hint}</p>}
    </div>
  )
}
