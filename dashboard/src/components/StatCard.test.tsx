import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatCard } from './StatCard'

describe('StatCard', () => {
  it('renders the label and value', () => {
    render(<StatCard label="CPU" value="42%" />)

    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByText('42%')).toBeInTheDocument()
  })

  it('renders a hint when provided', () => {
    render(<StatCard label="Disk" value="78%" hint="400 GB of 512 GB" />)

    expect(screen.getByText('400 GB of 512 GB')).toBeInTheDocument()
  })

  it('omits the hint element entirely when not provided', () => {
    const { container } = render(<StatCard label="Disk" value="78%" />)

    // Three <p> tags (label, value, hint) would mean an empty hint paragraph
    // rendered anyway, which is a layout gap a caller did not ask for.
    expect(container.querySelectorAll('p')).toHaveLength(2)
  })

  it('renders a numeric value', () => {
    render(<StatCard label="Cores" value={8} />)

    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('renders a hint of 0, not just a truthy one', () => {
    // A naive `{hint && <p>...}` check would silently drop a hint whose
    // value is the number 0 — a real value a page could legitimately pass.
    const { container } = render(<StatCard label="Errors" value="none" hint={0} />)

    expect(container.querySelectorAll('p')).toHaveLength(3)
  })
})
