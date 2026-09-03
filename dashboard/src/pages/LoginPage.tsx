import { useState, type FormEvent } from 'react'

import { login } from '../api/client'
import type { CurrentUser } from '../api/types'
import { describeLoginError } from '../lib/errors'
import styles from './LoginPage.module.css'

interface LoginPageProps {
  /** Called with the account the backend confirmed. AuthContext supplies this;
   *  the page itself holds no session state, because the session is a cookie
   *  the browser manages and there is nothing here to keep. */
  onAuthenticated: (user: CurrentUser) => void
}

/**
 * The one route outside AppShell.
 *
 * It renders no sidebar and starts no polling, deliberately: everything the
 * shell fetches is now behind authentication, so a login page built inside it
 * would fire a handful of requests it is guaranteed to get 401s for, and each
 * of those would ask the app to redirect to the page already on screen.
 */
export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      onAuthenticated(await login(username, password))
    } catch (cause) {
      setError(describeLoginError(cause))
      // Only the password: making someone retype a username they got right is
      // friction with no security value, since the backend will not say which
      // half was wrong anyway.
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <p className={styles.brand}>SysWatch</p>
        <p className={styles.hint}>Sign in to continue.</p>

        <form className={styles.form} onSubmit={handleSubmit}>
          <label className={styles.field}>
            <span>Username</span>
            <input
              type="text"
              name="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </label>

          <label className={styles.field}>
            <span>Password</span>
            <input
              type="password"
              name="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          {/* role=alert so a screen reader hears the failure, which is
              otherwise a silent colour change well below the button. */}
          {error !== null && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          <button type="submit" className={styles.submit} disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
