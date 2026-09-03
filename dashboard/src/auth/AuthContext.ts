import { createContext, useContext } from 'react'

import type { CurrentUser } from '../api/types'

/**
 * - `checking`: the first `/auth/me` has not answered yet. Nothing should
 *   render a decision on this, including the login page — see AuthProvider.
 * - `authenticated` / `anonymous`: settled.
 */
export type AuthStatus = 'checking' | 'authenticated' | 'anonymous'

export interface AuthValue {
  status: AuthStatus
  user: CurrentUser | null
  /** True only for a logged-in admin. Used to decide what to *offer*; the
   *  backend is what decides what is allowed. */
  isAdmin: boolean
  /** Adopt the account a successful login returned. */
  signIn: (user: CurrentUser) => void
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)

  if (value === null) {
    // A component reading auth outside the provider would otherwise silently
    // behave as if nobody were logged in, which looks like a login bug rather
    // than the wiring mistake it is.
    throw new Error('useAuth must be used inside an AuthProvider')
  }

  return value
}
