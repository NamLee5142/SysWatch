import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { renderWithAuth, testHost } from '../test/renderWithAuth'
import { HostSelector } from './HostSelector'

describe('HostSelector', () => {
  it('shows the host as plain text when there is only one', () => {
    // Most installs are one machine forever. A dropdown holding a single
    // option is a control that cannot do anything, sitting in the header.
    renderWithAuth(<HostSelector />, { hosts: [testHost('devbox')] })

    expect(screen.getByText('devbox')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('offers a choice once a second machine reports', () => {
    renderWithAuth(<HostSelector />, {
      hosts: [testHost('devbox'), testHost('buildbox')],
    })

    const select = screen.getByRole('combobox')
    expect(select).toHaveValue('devbox')
    expect(screen.getByRole('option', { name: 'buildbox' })).toBeInTheDocument()
  })

  it('reports the chosen host', async () => {
    const selectHost = vi.fn()
    renderWithAuth(<HostSelector />, {
      hosts: [testHost('devbox'), testHost('buildbox')],
      selectHost,
    })

    await userEvent.selectOptions(screen.getByRole('combobox'), 'buildbox')

    expect(selectHost).toHaveBeenCalledWith('buildbox')
  })

  it('is labelled for a screen reader', () => {
    // Sighted users read it as "the machine" from its position in the header.
    // A screen reader has no position to read.
    renderWithAuth(<HostSelector />, {
      hosts: [testHost('devbox'), testHost('buildbox')],
    })

    expect(screen.getByRole('combobox', { name: /host/i })).toBeInTheDocument()
  })

  it('shows a dash when nothing has reported', () => {
    // A fresh install before the first collection. Not an error.
    renderWithAuth(<HostSelector />, { hosts: [], hostName: null })

    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows nothing at all while the first answer is outstanding', () => {
    // A dash that becomes a hostname a moment later reads as "the agent is
    // down, no wait, it is fine" every time the page loads.
    renderWithAuth(<HostSelector />, { hosts: [], hostName: null, hostsLoading: true })

    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })
})
