import { Skeleton } from './Skeleton'

interface TableSkeletonRowsProps {
  columns: number
  rows?: number
}

/**
 * A handful of placeholder <tr> rows, meant to sit inside a caller's own
 * <tbody> — not a full table. The real <thead> stays visible during loading
 * on both pages that use this (System's host list, History's snapshot
 * table), so column headers do not flash in only once data arrives.
 */
export function TableSkeletonRows({ columns, rows = 5 }: TableSkeletonRowsProps) {
  return (
    <>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <tr key={rowIndex}>
          {Array.from({ length: columns }, (_, columnIndex) => (
            <td key={columnIndex}>
              <Skeleton height={14} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}
