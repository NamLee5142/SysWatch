import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './AuthContext'

/**
 * A layout route that admits only an authenticated caller.
 *
 * This is a redirect, not a security control — the backend refuses every one
 * of these endpoints without a session regardless of what the browser renders.
 * What it buys is that someone whose session ended sees a login form instead of
 * a dashboard full of failed requests.
 */
export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status !== 'authenticated') {
    // Remember where they were headed so logging in resumes it, rather than
    // dumping everyone on Overview and making them navigate again.
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  }

  return <Outlet />
}
