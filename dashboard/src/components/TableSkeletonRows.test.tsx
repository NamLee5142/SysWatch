import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TableSkeletonRows } from './TableSkeletonRows'

function renderRows(props: { columns: number; rows?: number }) {
  return render(
    <table>
      <tbody>
        <TableSkeletonRows {...props} />
      </tbody>
    </table>,
  )
}

describe('TableSkeletonRows', () => {
  it('defaults to 5 rows', () => {
    renderRows({ columns: 3 })

    expect(screen.getAllByRole('row')).toHaveLength(5)
  })

  it('renders the requested row count', () => {
    renderRows({ columns: 3, rows: 2 })

    expect(screen.getAllByRole('row')).toHaveLength(2)
  })

  it('renders exactly `columns` cells per row', () => {
    renderRows({ columns: 4, rows: 1 })

    expect(screen.getAllByRole('cell')).toHaveLength(4)
  })

  it('leaves the caller free to keep its own real <thead>', () => {
    // This component renders only <tr> rows for a <tbody>; it must not
    // assume or emit a header of its own.
    const { container } = renderRows({ columns: 3 })

    expect(container.querySelector('thead')).not.toBeInTheDocument()
  })
})
