import { render, type RenderResult } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import type { ReactNode } from 'react'

import type { CurrentUser } from '../api/types'
import { AuthContext, type AuthValue } from '../auth/AuthContext'

export const TEST_ADMIN: CurrentUser = { username: 'root', role: 'admin' }
export const TEST_VIEWER: CurrentUser = { username: 'viv', role: 'viewer' }

interface Options {
  /** null renders an anonymous caller. */
  user?: CurrentUser | null
  path?: string
  signIn?: AuthValue['signIn']
  signOut?: AuthValue['signOut']
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
  const { user = TEST_ADMIN, path = '/', signIn = vi.fn(), signOut = vi.fn() } = options

  const value: AuthValue = {
    status: user === null ? 'anonymous' : 'authenticated',
    user,
    isAdmin: user?.role === 'admin',
    signIn,
    signOut,
  }

  return render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </AuthContext.Provider>,
  )
}
