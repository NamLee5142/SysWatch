import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  createAlertRule,
  deleteAlertRule,
  getActiveAlerts,
  getAlerts,
  listAlertRules,
  updateAlertRule,
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
    createAlertRule: vi.fn(),
    updateAlertRule: vi.fn(),
    deleteAlertRule: vi.fn(),
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
  vi.mocked(createAlertRule).mockReset()
  vi.mocked(updateAlertRule).mockReset()
  vi.mocked(deleteAlertRule).mockReset()
})

describe('AlertsPage', () => {
  it('renders a firing alert with its value and threshold in the metric unit', async () => {
    resolveAll()

    renderWithAuth(<AlertsPage />)

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

    renderWithAuth(<AlertsPage />)

    const heading = await screen.findByRole('heading', { name: /Active/ })
    expect(heading).toHaveTextContent('2')
  })

  it('shows a success empty state when nothing is firing, not an error', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    renderWithAuth(<AlertsPage />)

    expect(await screen.findByText('No active alerts.')).toBeInTheDocument()
  })

  it('lists resolved alerts in their own section', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({
      items: [alert({ id: 5, state: 'ok', ruleName: 'Memory usage high', metric: 'memory', value: 40 })],
      count: 1,
    })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    renderWithAuth(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /Memory usage high/ })
    expect(within(row).getByText('Resolved')).toBeInTheDocument()
  })

  it('lists rules read-only with a friendly metric label and condition', async () => {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({
      items: [{ ...RULE, name: 'Process count high', metric: 'processes', operator: 'gt', threshold: 500, enabled: false }],
    })

    renderWithAuth(<AlertsPage />)

    const row = await screen.findByRole('row', { name: /Process count high/ })
    expect(within(row).getByText('Process count')).toBeInTheDocument()
    expect(within(row).getByText('> 500')).toBeInTheDocument()
    expect(within(row).getByText('No')).toBeInTheDocument()
  })

  it('shows a loading skeleton for the active section before it resolves', async () => {
    vi.mocked(getActiveAlerts).mockReturnValue(neverSettles())
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    renderWithAuth(<AlertsPage />)

    expect(await screen.findByText('Loading active alerts')).toBeInTheDocument()
  })

  it('shows an error message for a section whose fetch fails, not a stuck skeleton', async () => {
    vi.mocked(getActiveAlerts).mockRejectedValue(new Error('boom'))
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue({ items: [] })

    renderWithAuth(<AlertsPage />)

    await waitFor(() => expect(screen.getByText('Unable to load active alerts.')).toBeInTheDocument())
    expect(screen.queryByText('Loading active alerts')).not.toBeInTheDocument()
  })
})


// --- role-aware rule controls ------------------------------------------------

describe('AlertsPage rule controls', () => {
  const RULES = { items: [RULE] }

  function quietAlerts() {
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
    vi.mocked(getAlerts).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(listAlertRules).mockResolvedValue(RULES)
  }

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('offers no rule controls to a viewer', async () => {
    quietAlerts()

    renderWithAuth(<AlertsPage />, { user: TEST_VIEWER })

    await screen.findByRole('row', { name: /CPU usage critical/ })
    expect(screen.queryByRole('button', { name: 'Add rule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Disable' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('offers them to an admin', async () => {
    quietAlerts()

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })

    await screen.findByRole('row', { name: /CPU usage critical/ })
    expect(screen.getByRole('button', { name: 'Add rule' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('creates a rule and refreshes the list', async () => {
    quietAlerts()
    vi.mocked(createAlertRule).mockResolvedValue(RULE)

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    await userEvent.click(await screen.findByRole('button', { name: 'Add rule' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Disk full')
    await userEvent.selectOptions(screen.getByLabelText('Metric'), 'disk')
    await userEvent.click(screen.getByRole('button', { name: 'Create rule' }))

    await waitFor(() =>
      expect(createAlertRule).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Disk full', metric: 'disk', operator: 'gt', threshold: 90 }),
      ),
    )
    // Waiting up to five seconds for the poll to show your own click reads as
    // the click not having worked.
    expect(listAlertRules).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(screen.queryByLabelText('Name')).not.toBeInTheDocument())
  })

  it('toggles a rule with a partial update', async () => {
    quietAlerts()
    vi.mocked(updateAlertRule).mockResolvedValue({ ...RULE, enabled: false })

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    await userEvent.click(await screen.findByRole('button', { name: 'Disable' }))

    await waitFor(() => expect(updateAlertRule).toHaveBeenCalledWith(RULE.id, { enabled: false }))
  })

  it('asks before deleting, and does nothing if refused', async () => {
    quietAlerts()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    // Deleting a rule orphans its alert history; it should not happen on one
    // stray click.
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteAlertRule).not.toHaveBeenCalled()
  })

  it('deletes when confirmed', async () => {
    quietAlerts()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(deleteAlertRule).mockResolvedValue(undefined)

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(deleteAlertRule).toHaveBeenCalledWith(RULE.id))
  })

  it('explains a 403 rather than showing a generic failure', async () => {
    quietAlerts()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(deleteAlertRule).mockRejectedValue(new ApiError(403, 'Administrator access required'))

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    // Hiding the controls is a courtesy; require_admin on the backend is what
    // actually refuses. Anyone who gets here should be told which it was.
    expect(await screen.findByRole('alert')).toHaveTextContent('Only an admin can change alert rules.')
  })

  it('keeps the form open when creation fails', async () => {
    quietAlerts()
    vi.mocked(createAlertRule).mockRejectedValue(new ApiError(422, 'Input should be a finite number'))

    renderWithAuth(<AlertsPage />, { user: TEST_ADMIN })
    await userEvent.click(await screen.findByRole('button', { name: 'Add rule' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Bad rule')
    await userEvent.click(screen.getByRole('button', { name: 'Create rule' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Input should be a finite number')
    // Closing it would throw away what they typed.
    expect(screen.getByLabelText('Name')).toHaveValue('Bad rule')
  })
})
