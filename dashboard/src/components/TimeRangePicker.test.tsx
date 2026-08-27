import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TIME_RANGES } from '../lib/timeRanges'
import { TimeRangePicker } from './TimeRangePicker'

describe('TimeRangePicker', () => {
  it('renders every configured range as an option', () => {
    render(<TimeRangePicker value={TIME_RANGES[0]} onChange={vi.fn()} />)

    for (const range of TIME_RANGES) {
      expect(screen.getByRole('radio', { name: range.label })).toBeInTheDocument()
    }
  })

  it('marks only the current value as checked', () => {
    render(<TimeRangePicker value={TIME_RANGES[2]} onChange={vi.fn()} />)

    expect(screen.getByRole('radio', { name: TIME_RANGES[2].label })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: TIME_RANGES[0].label })).toHaveAttribute('aria-checked', 'false')
  })

  it('calls onChange with the selected range object, not just its label', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<TimeRangePicker value={TIME_RANGES[0]} onChange={onChange} />)

    await user.click(screen.getByRole('radio', { name: '24h' }))

    expect(onChange).toHaveBeenCalledWith(TIME_RANGES[2])
  })

  it('does not call onChange when clicking a range that is not selected yet stays uncontrolled', async () => {
    // The picker does not manage its own selected state — value is fully
    // controlled by the caller, so nothing changes here until a new `value`
    // prop arrives.
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<TimeRangePicker value={TIME_RANGES[0]} onChange={onChange} />)

    await user.click(screen.getByRole('radio', { name: '6h' }))

    expect(screen.getByRole('radio', { name: '1h' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: '6h' })).toHaveAttribute('aria-checked', 'false')
  })
})
