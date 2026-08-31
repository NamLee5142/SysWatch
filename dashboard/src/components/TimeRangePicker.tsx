import { TIME_RANGES, type TimeRange } from '../lib/timeRanges'
import styles from './TimeRangePicker.module.css'

interface TimeRangePickerProps {
  value: TimeRange
  onChange: (range: TimeRange) => void
}

/** 1h / 6h / 24h / 7d, for the trend chart on each metric page. */
export function TimeRangePicker({ value, onChange }: TimeRangePickerProps) {
  return (
    <div className={styles.picker} role="radiogroup" aria-label="Time range">
      {TIME_RANGES.map((range) => {
        const active = range.label === value.label

        return (
          <button
            key={range.label}
            type="button"
            role="radio"
            aria-checked={active}
            className={active ? `${styles.option} ${styles.optionActive}` : styles.option}
            onClick={() => onChange(range)}
          >
            {range.label}
          </button>
        )
      })}
    </div>
  )
}
