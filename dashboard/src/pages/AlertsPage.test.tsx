import { render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getActiveAlerts, getAlerts, listAlertRules } from '../api/client'
import type { Alert, AlertRule } from '../api/types'
import { AlertsPage } from './AlertsPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getActiveAlerts: vi.fn(),
    getAlerts: vi.fn(),
    listAlertRules: vi.fn(),
  }
})

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    ruleId: 10,
    ruleName: 'CPU usage critical',
    metric: 'cpu',
    operator: 'gt',
    threshold: 95,
    severity: 'critical',
    hostName: 'devbox',
    state: 'firing',
    value: 97.4,
    triggeredAt: new Date().toISOString(),
    resolvedAt: null,
    lastSeenAt: new Date().toISOString(),
    ...overrides,
  }
}

const RULE: AlertRule = {
  id: 10,
  name: 'CPU usage critical',
  metric: 'cpu',
  operator: 'gt',
  threshold: 95,
  severity: 'critical',
  enabled: true,
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
}

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

function resolveAll() {
  vi.mocked(getActiveAlerts).mockResolvedValue({ items: [alert()] })
  vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
  // Empty so the rules table cannot also match on the alert's ruleName.
  vi.mocked(listAlertRules).mockResolvedValue({ items: [] })
}

beforeEach(() => {
  vi.mocked(getActiveAlerts).mockReset()
  vi.mocked(getAlerts).mockReset()
  vi.mocked(listAlertRules).mockReset()
})

describe('AlertsPage', () => {
  it('renders a firing alert with its value and threshold in the metric unit', async () => {
    resolveAll()

    render(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /CPU usage critical/ })
    expect(within(row).getByText('Critical')).toBeInTheDocument()
    expect(within(row).getByText('devbox')).toBeInTheDocument()
    expect(within(row).getByText('97.4%')).toBeInTheDocument()
    expect(within(row).getByText('> 95.0%')).toBeInTheDocument()
    expect(within(row).getByText('Firing')).toBeInTheDocument()
  })

  it('shows the active count next to the heading', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [alert({ id: 1 }), alert({ id: 2 })] })
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    render(<AlertsPage />)

    const heading = await screen.findByRole('heading', { name: /Active/ })
    expect(heading).toHaveTextContent('2')
  })

  it('shows a success empty state when nothing is firing, not an error', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    render(<AlertsPage />)

    expect(await screen.findByText('No active alerts.')).toBeInTheDocument()
  })

  it('lists resolved alerts in their own section', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({
      items: [alert({ id: 5, state: 'ok', ruleName: 'Memory usage high', metric: 'memory', value: 40 })],
      count: 1,
    })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    render(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /Memory usage high/ })
    expect(within(row).getByText('Resolved')).toBeInTheDocument()
  })

  it('lists rules read-only with a friendly metric label and condition', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({
      items: [{ ...RULE, name: 'Process count high', metric: 'processes', operator: 'gt', threshold: 500, enabled: false }],
    })

    render(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /Process count high/ })
    expect(within(row).getByText('Process count')).toBeInTheDocument()
    expect(within(row).getByText('> 500')).toBeInTheDocument()
    expect(within(row).getByText('No')).toBeInTheDocument()
  })

  it('shows a loading skeleton for the active section before it resolves', async () => {
    vi.mocked(getActiveAlerts).mockReturnValue(neverSettles())
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    render(<AlertsPage />)

    expect(await screen.findByText('Loading active alerts')).toBeInTheDocument()
  })

  it('shows an error message for a section whose fetch fails, not a stuck skeleton', async () => {
    vi.mocked(getActiveAlerts).mockRejectedValue(new Error('boom'))
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    render(<AlertsPage />)

    await waitFor(() => expect(screen.getByText('Unable to load active alerts.')).toBeInTheDocument())
    expect(screen.queryByText('Loading active alerts')).not.toBeInTheDocument()
  })
})
