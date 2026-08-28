import styles from './Skeleton.module.css'

interface SkeletonProps {
  width?: string | number
  height?: string | number
  radius?: string | number
  className?: string
}

/**
 * A single shimmering placeholder block. Purely decorative — the accessible
 * "loading" announcement belongs on the container around a group of these
 * (role="status" + a .visually-hidden label), not on every individual bar,
 * or a screen reader announces "Loading" once per block instead of once per
 * page.
 */
export function Skeleton({ width = '100%', height = '1em', radius, className }: SkeletonProps) {
  return (
    <span
      className={className ? `${styles.skeleton} ${className}` : styles.skeleton}
      style={{ width, height, borderRadius: radius }}
      aria-hidden="true"
    />
  )
}
