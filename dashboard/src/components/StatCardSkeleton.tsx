import { Skeleton } from './Skeleton'
import cardStyles from './StatCard.module.css'

/**
 * Same outer shape as StatCard (reuses its CSS module): a label-height line
 * above a taller value-height line, so the skeleton and the real tile it is
 * replaced by do not visibly shift.
 *
 * Each line is wrapped in a <p>, matching StatCard's own markup — .card has
 * no flex layout of its own (unlike GaugeCard's), it relies on block-level
 * children to stack; two bare inline-block Skeletons here would sit side by
 * side instead.
 */
export function StatCardSkeleton() {
  return (
    <div className={cardStyles.card}>
      <p className={cardStyles.label}>
        <Skeleton width={60} height={13} />
      </p>
      <p className={cardStyles.value}>
        <Skeleton width={110} height={28} radius={4} />
      </p>
    </div>
  )
}
