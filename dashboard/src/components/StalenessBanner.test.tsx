import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { STALE_AFTER_MS, StalenessBanner } from './StalenessBanner'

const NOW = Date.now()

function ago(ms: number): string {
  return new Date(NOW - ms).toISOString()
}

/** Looking at the machine the backend polls, whose data is current. */
function props(overrides: Partial<Parameters<typeof StalenessBanner>[0]> = {}) {
  return {
    agentState: 'up' as const,
    agentHost: 'devbox',
    hostName: 'devbox',
    lastCollectedAt: ago(5_000),
    ...overrides,
  }
}

describe('StalenessBanner', () => {
  it('renders nothing when the agent is up and the data is current', () => {
    const { container } = render(<StalenessBanner {...props()} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the agent state is unknown', () => {
    // Unknown means "have not confirmed either way yet" (polling just
    // started, or is disabled) — not evidence of a problem, so it must not
    // read as one.
    const { container } = render(<StalenessBanner {...props({ agentState: 'unknown' })} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders a warning when the polled agent is down', () => {
    render(<StalenessBanner {...props({ agentState: 'down' })} />)

    expect(
      screen.getByText('Agent unreachable — showing the last data received.'),
    ).toBeInTheDocument()
  })

  it('announces itself as a status region for assistive tech', () => {
    render(<StalenessBanner {...props({ agentState: 'down' })} />)

    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  // --- whose outage is it? ------------------------------------------------

  it('says nothing about the polled agent while looking at another host', () => {
    // The backend polls one machine. Reporting its outage against a pushed
    // host's name would be reporting the wrong machine's problem, which is
    // worse than saying nothing: it sends somebody to check a healthy box.
    const { container } = render(
      <StalenessBanner
        {...props({ agentState: 'down', agentHost: 'devbox', hostName: 'buildbox' })}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('says nothing about the polled agent before it has ever answered', () => {
    // agentHost is null until then, so there is no host to match against.
    const { container } = render(
      <StalenessBanner {...props({ agentState: 'down', agentHost: null })} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  // --- has this host reported recently? -----------------------------------

  it('reports a host that has stopped sending, whichever host it is', () => {
    render(
      <StalenessBanner
        {...props({
          agentState: 'up',
          agentHost: 'devbox',
          hostName: 'buildbox',
          lastCollectedAt: ago(STALE_AFTER_MS + 60_000),
        })}
      />,
    )

    expect(screen.getByText(/No new data from buildbox/)).toBeInTheDocument()
  })

  it('counts the silence up rather than freezing at the moment it went stale', () => {
    // A dashboard left open overnight should say how long it has been, not
    // how long it had been when somebody last looked.
    render(<StalenessBanner {...props({ lastCollectedAt: ago(10 * 60 * 1000) })} />)

    expect(screen.getByRole('status').querySelector('time')).toBeInTheDocument()
  })

  it('leaves a merely slow agent alone', () => {
    // Just inside the threshold. The dashboard cannot know a given agent's
    // collection interval, so it must not accuse one that is simply unhurried.
    const { container } = render(
      <StalenessBanner {...props({ lastCollectedAt: ago(STALE_AFTER_MS - 30_000) })} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when no host has reported at all', () => {
    // A fresh install. There is no staleness without a first reading.
    const { container } = render(
      <StalenessBanner
        {...props({ hostName: null, agentHost: null, lastCollectedAt: null })}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('prefers the agent-down message when both apply', () => {
    // The polled agent is down *and* its data has aged past the threshold.
    // "Agent unreachable" is the more specific and more actionable of the two.
    render(
      <StalenessBanner
        {...props({ agentState: 'down', lastCollectedAt: ago(STALE_AFTER_MS + 60_000) })}
      />,
    )

    expect(
      screen.getByText('Agent unreachable — showing the last data received.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/No new data from/)).not.toBeInTheDocument()
  })

  it('starts warning while the page sits open, without waiting for anything else', async () => {
    // The reason it keeps its own clock. A dashboard left open must notice a
    // host going quiet by itself, not when some unrelated poll happens to
    // re-render it.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      render(<StalenessBanner {...props({ lastCollectedAt: new Date().toISOString() })} />)
      expect(screen.queryByRole('status')).not.toBeInTheDocument()

      await vi.advanceTimersByTimeAsync(STALE_AFTER_MS + 61_000)

      expect(screen.getByText(/No new data from devbox/)).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
