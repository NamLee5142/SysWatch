import { render, type RenderResult } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import type { ReactNode } from 'react'

import type { CurrentUser, Host } from '../api/types'
import { AuthContext, type AuthValue } from '../auth/AuthContext'
import { SelectedHostContext, type SelectedHostValue } from '../hosts/SelectedHostContext'

export const TEST_ADMIN: CurrentUser = { username: 'root', role: 'admin' }
export const TEST_VIEWER: CurrentUser = { username: 'viv', role: 'viewer' }

export function testHost(hostName: string): Host {
  return { hostName, lastCollectedAt: '2026-09-08T10:00:00Z', snapshotCount: 1 }
}

/** One host reporting, which is what every install looks like until a second
 *  machine is added - and what every test written before hosts existed
 *  implicitly assumed. */
export const TEST_HOSTS: Host[] = [testHost('devbox')]

interface Options {
  /** null renders an anonymous caller. */
  user?: CurrentUser | null
  path?: string
  signIn?: AuthValue['signIn']
  signOut?: AuthValue['signOut']
  /** Which machines are reporting. Defaults to one, named devbox. */
  hosts?: Host[]
  /** Which one is shown. Defaults to the first, or null when there are none. */
  hostName?: string | null
  hostsLoading?: boolean
  selectHost?: SelectedHostValue['select']
}

/**
 * Render inside a router and a known authentication state.
 *
 * The context is supplied directly rather than by mounting AuthProvider: these
 * tests are about what the app does with a given identity, and going through
 * the real provider would mean stubbing `/auth/me` in every file to arrange it.
 * AuthProvider has its own tests for how that state is arrived at.
 */
export function renderWithAuth(ui: ReactNode, options: Options = {}): RenderResult {
  const {
    user = TEST_ADMIN,
    path = '/',
    signIn = vi.fn(),
    signOut = vi.fn(),
    hosts = TEST_HOSTS,
    hostsLoading = false,
    selectHost = vi.fn(),
  } = options
  const hostName = 'hostName' in options ? options.hostName : (hosts[0]?.hostName ?? null)

  const value: AuthValue = {
    status: user === null ? 'anonymous' : 'authenticated',
    user,
    isAdmin: user?.role === 'admin',
    signIn,
    signOut,
  }

  // Supplied directly, like the auth value above and for the same reason:
  // these tests are about what a page does with a given selection, not about
  // how the selection is arrived at. SelectedHostProvider has its own tests.
  const selected: SelectedHostValue = {
    hosts,
    hostName: hostName ?? null,
    loading: hostsLoading,
    lastCollectedAt:
      hosts.find((host) => host.hostName === hostName)?.lastCollectedAt ?? null,
    select: selectHost,
  }

  return render(
    <AuthContext.Provider value={value}>
      <SelectedHostContext.Provider value={selected}>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </SelectedHostContext.Provider>
    </AuthContext.Provider>,
  )
}
