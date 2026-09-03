import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getActiveAlerts } from '../api/client'
import { AlertIndicator } from './AlertIndicator'

vi.mock('../api/client', () => ({
  getActiveAlerts: vi.fn(),
}))

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

function renderIndicator() {
  return render(
    <MemoryRouter>
      <AlertIndicator />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(getActiveAlerts).mockReset()
})

describe('AlertIndicator', () => {
  it('shows zero and a quiet label before the first poll resolves', () => {
    vi.mocked(getActiveAlerts).mockReturnValue(neverSettles())

    renderIndicator()

    const link = screen.getByRole('link', { name: 'No active alerts' })
    expect(link).toHaveTextContent('0')
  })

  it('is still rendered when there are no active alerts, not hidden', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })

    renderIndicator()

    await waitFor(() => expect(screen.getByRole('link', { name: 'No active alerts' })).toBeInTheDocument())
  })

  it('shows the count and a pluralised label when alerts are firing', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [{}, {}, {}] } as never)

    renderIndicator()

    const link = await screen.findByRole('link', { name: '3 active alerts' })
    expect(link).toHaveTextContent('3')
    expect(link).toHaveAttribute('href', '/alerts')
  })

  it('uses the singular for exactly one alert', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [{}] } as never)

    renderIndicator()

    await waitFor(() => expect(screen.getByRole('link', { name: '1 active alert' })).toBeInTheDocument())
  })

  it('falls back to zero rather than showing an error when the poll fails', async () => {
    vi.mocked(getActiveAlerts).mockRejectedValue(new Error('boom'))

    renderIndicator()

    // Give the rejection a tick to land.
    await waitFor(() => expect(getActiveAlerts).toHaveBeenCalled())
    expect(screen.getByRole('link', { name: 'No active alerts' })).toHaveTextContent('0')
  })
})
