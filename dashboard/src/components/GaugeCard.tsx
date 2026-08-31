import { Gauge } from './Gauge'
import styles from './GaugeCard.module.css'

interface GaugeCardProps {
  value: number
  // Optional: Overview needs it to tell its CPU tile apart from five others;
  // a metric's own page (CPU) already says so in the page title, so this
  // tile there can drop the redundant label.
  label?: string
  hint?: string
  size?: number
}

/** A Gauge in a bordered tile, with an optional label and hint below it.
 *  Shared by Overview's CPU tile and the CPU page's own headline gauge, so
 *  the same metric reads as the same visual element wherever it appears. */
export function GaugeCard({ value, label, hint, size }: GaugeCardProps) {
  return (
    <div className={styles.card}>
      <Gauge value={value} size={size} />
      {label && <span className={styles.label}>{label}</span>}
      {hint && <span className={styles.hint}>{hint}</span>}
    </div>
  )
}
