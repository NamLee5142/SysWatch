import { describe, expect, it } from 'vitest'

import { formatGB, formatMemoryMB, formatRelativeTime } from './format'

describe('formatMemoryMB', () => {
  it('renders whole MB below 1 GB', () => {
    expect(formatMemoryMB(512)).toBe('512 MB')
  })

  it('rounds a fractional MB value below 1 GB', () => {
    expect(formatMemoryMB(511.6)).toBe('512 MB')
  })

  it('switches to GB with one decimal at exactly 1024 MB', () => {
    expect(formatMemoryMB(1024)).toBe('1.0 GB')
  })

  it('renders GB with one decimal above the threshold', () => {
    expect(formatMemoryMB(16384)).toBe('16.0 GB')
  })

  it('does not round GB to a whole number', () => {
    expect(formatMemoryMB(1536)).toBe('1.5 GB')
  })
})

describe('formatGB', () => {
  it('renders a whole GB value', () => {
    expect(formatGB(512)).toBe('512 GB')
  })

  it('rounds a fractional GB value', () => {
    expect(formatGB(111.7)).toBe('112 GB')
  })

  it('renders zero explicitly rather than an empty string', () => {
    expect(formatGB(0)).toBe('0 GB')
  })
})

describe('formatRelativeTime', () => {
  const NOW = new Date('2026-08-25T12:00:00Z')

  function secondsAgo(seconds: number): string {
    return new Date(NOW.getTime() - seconds * 1000).toISOString()
  }

  it('renders "just now" for anything under 5 seconds old', () => {
    expect(formatRelativeTime(secondsAgo(4), NOW)).toBe('just now')
  })

  it('renders whole seconds between 5s and 1 minute', () => {
    expect(formatRelativeTime(secondsAgo(42), NOW)).toBe('42s ago')
  })

  it('renders whole minutes between 1 minute and 1 hour', () => {
    expect(formatRelativeTime(secondsAgo(5 * 60), NOW)).toBe('5m ago')
  })

  it('renders whole hours between 1 hour and 1 day', () => {
    expect(formatRelativeTime(secondsAgo(3 * 60 * 60), NOW)).toBe('3h ago')
  })

  it('renders whole days at 1 day or older', () => {
    expect(formatRelativeTime(secondsAgo(2 * 24 * 60 * 60), NOW)).toBe('2d ago')
  })

  it('treats a timestamp fractionally in the future as "just now" rather than negative', () => {
    // Clock skew between the agent, the backend, and the browser is real; a
    // negative diff must not render as "-1s ago". Guaranteed by the branch
    // order (smallest threshold first) rather than a separate clamp — any
    // negative value is already < 5.
    const almostNow = new Date(NOW.getTime() + 400).toISOString()
    expect(formatRelativeTime(almostNow, NOW)).toBe('just now')
  })
})
