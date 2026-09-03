import { Navigate, useLocation } from 'react-router-dom'

import { LoginPage } from '../pages/LoginPage'
import { useAuth } from './AuthContext'

/**
 * Puts the login form on a route and decides where a successful login lands.
 *
 * The page itself stays free of routing and auth state, which is what lets it
 * be tested as a form rather than as a screen in a flow.
 */
export function LoginRoute() {
  const { status, signIn } = useAuth()
  const location = useLocation()

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  if (status === 'authenticated') {
    // Covers both cases: arriving at /login while already signed in, and the
    // re-render immediately after signIn(). No imperative navigate() needed —
    // the redirect is just what this route renders once the state settles.
    return <Navigate to={from} replace />
  }

  return <LoginPage onAuthenticated={signIn} />
}
