import { Skeleton } from './Skeleton'
import cardStyles from './GaugeCard.module.css'

interface GaugeCardSkeletonProps {
  size?: number
}

/** Same outer shape as GaugeCard (reuses its CSS module), so a skeleton
 *  layout and the real content it is replaced by do not visibly shift. */
export function GaugeCardSkeleton({ size = 120 }: GaugeCardSkeletonProps) {
  return (
    <div className={cardStyles.card}>
      <Skeleton width={size} height={size} radius="50%" />
      <Skeleton width={80} height={12} />
    </div>
  )
}
