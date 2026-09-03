import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { getMe, logout as logoutRequest, setUnauthorizedHandler } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthContext, type AuthStatus, type AuthValue } from './AuthContext'
import styles from './AuthProvider.module.css'

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [status, setStatus] = useState<AuthStatus>('checking')
  const [user, setUser] = useState<CurrentUser | null>(null)

  // One call, on mount. The session is an HttpOnly cookie, so the page cannot
  // read it and has to ask the backend who it is talking to.
  useEffect(() => {
    let cancelled = false

    getMe()
      .then((current) => {
        if (cancelled) return
        setUser(current)
        setStatus('authenticated')
      })
      .catch(() => {
        // Any failure lands here, including the backend being unreachable.
        // Treating that as anonymous sends the visitor to the login page,
        // which reports the real reason when they try — better than a screen
        // that claims they are logged in to something that is not answering.
        if (cancelled) return
        setUser(null)
        setStatus('anonymous')
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Any request can be the one that finds the session gone. They all report it
  // here rather than each deciding what to do about it.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      setStatus('anonymous')
    })

    return () => setUnauthorizedHandler(null)
  }, [])

  const signIn = useCallback((current: CurrentUser) => {
    setUser(current)
    setStatus('authenticated')
  }, [])

  const signOut = useCallback(async () => {
    try {
      await logoutRequest()
    } catch {
      // Swallowed, not rethrown. Callers fire this from an onClick and have
      // nothing useful to do with the failure, so rethrowing would only produce
      // an unhandled rejection in the console every time someone signs out
      // while the backend is down.
    }

    // Either way. Staying "logged in" locally because the backend did not
    // answer leaves someone looking at a dashboard they have asked to leave.
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ status, user, isAdmin: user?.role === 'admin', signIn, signOut }),
    [status, user, signIn, signOut],
  )

  if (status === 'checking') {
    // Not the login page. A refresh with a perfectly good session would
    // otherwise flash a login form and then replace it, which reads as having
    // been logged out.
    return (
      <div className={styles.checking} role="status">
        <span className="visually-hidden">Checking your session</span>
      </div>
    )
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
