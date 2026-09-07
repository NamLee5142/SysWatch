import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  acknowledgeAlert,
  getActiveAlerts,
  getAlerts,
  listAlertRules,
  silenceAlertRule,
  unsilenceAlertRule,
} from '../api/client'
import type { Alert, AlertRule } from '../api/types'
import { renderWithAuth, TEST_ADMIN, TEST_VIEWER } from '../test/renderWithAuth'
import { AlertsPage } from './AlertsPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getActiveAlerts: vi.fn(),
    getAlerts: vi.fn(),
    listAlertRules: vi.fn(),
    acknowledgeAlert: vi.fn(),
    silenceAlertRule: vi.fn(),
    unsilenceAlertRule: vi.fn(),
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
    acknowledgedAt: null,
    acknowledgedBy: null,
    lastNotifiedAt: null,
    lastSeenAt: new Date().toISOString(),
    ...overrides,
  }
}

function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 10,
    name: 'CPU threshold rule',
    metric: 'cpu',
    operator: 'gt',
    threshold: 95,
    severity: 'critical',
    enabled: true,
    silencedUntil: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  }
}

function showing({ alerts = [alert()], rules = [rule()] } = {}) {
  vi.mocked(getActiveAlerts).mockResolvedValue({ items: alerts })
  vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
  vi.mocked(listAlertRules).mockResolvedValue({ items: rules })
}

beforeEach(() => {
  vi.mocked(getActiveAlerts).mockReset()
  vi.mocked(getAlerts).mockReset()
  vi.mocked(listAlertRules).mockReset()
  vi.mocked(acknowledgeAlert).mockReset()
  vi.mocked(silenceAlertRule).mockReset()
  vi.mocked(unsilenceAlertRule).mockReset()
})

describe('acknowledging an alert', () => {
  it('offers the button on a firing alert nobody has taken', async () => {
    showing()

    renderWithAuth(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /CPU usage critical/ })
    expect(within(row).getByRole('button', { name: 'Acknowledge' })).toBeInTheDocument()
  })

  it('sends the acknowledgement and refreshes', async () => {
    showing()
    vi.mocked(acknowledgeAlert).mockResolvedValue(alert({ acknowledgedBy: 'test-admin' }))

    renderWithAuth(<AlertsPage />)
    const row = await screen.findByRole('row', { name: /CPU usage critical/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Acknowledge' }))

    await waitFor(() => expect(acknowledgeAlert).toHaveBeenCalledWith(1))
    // Polled every few seconds, but waiting for that reads as the click not
    // having worked.
    expect(getActiveAlerts).toHaveBeenCalledTimes(2)
  })

  it('shows who acknowledged it, and stops offering the button', async () => {
    showing({ alerts: [alert({ acknowledgedAt: new Date().toISOString(), acknowledgedBy: 'sam' })] })

    renderWithAuth(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /CPU usage critical/ })
    expect(within(row).getByText('sam')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
  })

  it('lets a viewer acknowledge', async () => {
    // Not a configuration change: the person on shift saying they have seen it.
    showing()
    vi.mocked(acknowledgeAlert).mockResolvedValue(alert({ acknowledgedBy: 'test-viewer' }))

    renderWithAuth(<AlertsPage />, { user: TEST_VIEWER })
    const row = await screen.findByRole('row', { name: /CPU usage critical/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Acknowledge' }))

    await waitFor(() => expect(acknowledgeAlert).toHaveBeenCalledWith(1))
  })

  it('reports a failure instead of pretending it worked', async () => {
    showing()
    vi.mocked(acknowledgeAlert).mockRejectedValue(new Error('offline'))

    renderWithAuth(<AlertsPage />)
    const row = await screen.findByRole('row', { name: /CPU usage critical/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Acknowledge' }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})

describe('silencing a rule', () => {
  it('offers durations to an admin', async () => {
    showing()

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })

    const menu = await screen.findByRole('combobox', { name: /Silence CPU threshold rule/ })
    expect(within(menu).getByRole('option', { name: '4 hours' })).toBeInTheDocument()
  })

  it('sends the chosen duration', async () => {
    showing()
    vi.mocked(silenceAlertRule).mockResolvedValue(rule())

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    const menu = await screen.findByRole('combobox', { name: /Silence CPU threshold rule/ })
    await userEvent.selectOptions(menu, '240')

    await waitFor(() => expect(silenceAlertRule).toHaveBeenCalledWith(10, 240))
  })

  it('shows when a silence ends, and offers to lift it', async () => {
    const later = new Date(Date.now() + 60 * 60 * 1000).toISOString()
    showing({ rules: [rule({ silencedUntil: later })] })

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })

    const row = await screen.findByRole('row', { name: /CPU threshold rule/ })
    expect(within(row).getByRole('button', { name: 'Unsilence' })).toBeInTheDocument()
    expect(within(row).queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('treats an expired silence as no silence', async () => {
    // The backend already ignores it. Showing "Silenced" for a window that
    // closed yesterday would be a lie the user cannot correct.
    const earlier = new Date(Date.now() - 60 * 60 * 1000).toISOString()
    showing({ rules: [rule({ silencedUntil: earlier })] })

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })

    const row = await screen.findByRole('row', { name: /CPU threshold rule/ })
    expect(within(row).queryByRole('button', { name: 'Unsilence' })).not.toBeInTheDocument()
    expect(within(row).getByRole('combobox')).toBeInTheDocument()
  })

  it('lifts a silence', async () => {
    const later = new Date(Date.now() + 60 * 60 * 1000).toISOString()
    showing({ rules: [rule({ silencedUntil: later })] })
    vi.mocked(unsilenceAlertRule).mockResolvedValue(rule())

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    const row = await screen.findByRole('row', { name: /CPU threshold rule/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Unsilence' }))

    await waitFor(() => expect(unsilenceAlertRule).toHaveBeenCalledWith(10))
  })

  it('shows a viewer the silence but no way to change it', async () => {
    // The plan's acceptance condition. What actually stops them is
    // require_admin on the backend; hiding the control is the courtesy.
    const later = new Date(Date.now() + 60 * 60 * 1000).toISOString()
    showing({ rules: [rule({ silencedUntil: later })] })

    renderWithAuth(<AlertsPage />, { user: TEST_VIEWER })

    const row = await screen.findByRole('row', { name: /CPU threshold rule/ })
    expect(within(row).queryByRole('button', { name: 'Unsilence' })).not.toBeInTheDocument()
    expect(within(row).queryByRole('combobox')).not.toBeInTheDocument()
  })
})
