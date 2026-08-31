import { describeSnapshotError } from '../lib/errors'

interface SnapshotErrorMessageProps {
  error: unknown
  className?: string
}

export function SnapshotErrorMessage({ error, className }: SnapshotErrorMessageProps) {
  return <p className={className}>{describeSnapshotError(error)}</p>
}
