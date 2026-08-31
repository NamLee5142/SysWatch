import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NetworkError } from '../api/client'
import { SnapshotErrorMessage } from './SnapshotErrorMessage'

describe('SnapshotErrorMessage', () => {
  it('renders the message inside a paragraph', () => {
    render(<SnapshotErrorMessage error={new NetworkError(new Error())} />)

    expect(screen.getByText("Can't reach the backend. Check that it's running.")).toBeInTheDocument()
  })

  it('applies the given className, so callers keep their own placeholder styling', () => {
    const { container } = render(<SnapshotErrorMessage error={new Error()} className="my-class" />)

    expect(container.querySelector('p')).toHaveClass('my-class')
  })
})
