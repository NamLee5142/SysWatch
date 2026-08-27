import styles from './Gauge.module.css'

interface GaugeProps {
  // Percentage, 0-100. Values outside that range are clamped rather than
  // rejected — a metric briefly over 100 from rounding should still read as
  // "full", not break the ring.
  value: number
  label?: string
  size?: number
}

const RADIUS = 40
const STROKE_WIDTH = 8
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// No severity coloring (green/amber/red bands) here on purpose — thresholds
// and alerting are out of scope for this sprint. One accent color for every
// reading keeps the gauge from silently becoming the alert engine.
export function Gauge({ value, label, size = 120 }: GaugeProps) {
  const clamped = Math.min(100, Math.max(0, value))
  const dashOffset = CIRCUMFERENCE * (1 - clamped / 100)

  return (
    <div className={styles.gauge} style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={label ? `${label}: ${Math.round(clamped)}%` : `${Math.round(clamped)}%`}>
        <circle cx="50" cy="50" r={RADIUS} className={styles.track} strokeWidth={STROKE_WIDTH} fill="none" />
        <circle
          cx="50"
          cy="50"
          r={RADIUS}
          className={styles.value}
          strokeWidth={STROKE_WIDTH}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 50 50)"
        />
      </svg>
      <div className={styles.readout} aria-hidden="true">
        <span className={styles.percent}>{Math.round(clamped)}%</span>
        {label && <span className={styles.gaugeLabel}>{label}</span>}
      </div>
    </div>
  )
}
