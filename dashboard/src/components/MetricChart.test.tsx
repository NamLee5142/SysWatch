import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'

import type { SeriesPoint } from '../api/types'
import { MetricChart } from './MetricChart'

const POINTS: SeriesPoint[] = [
  { t: '2026-08-25T10:00:00Z', value: 20 },
  { t: '2026-08-25T11:00:00Z', value: 70 },
  { t: '2026-08-25T12:00:00Z', value: 45 },
]

beforeAll(() => {
  // jsdom has no layout engine, so Recharts' ResponsiveContainer measures a
  // 0x0 box and renders nothing underneath it. Stubbing a real size is what
  // lets the tests below see the actual chart instead of only its wrapper.
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      width: 600,
      height: 220,
      top: 0,
      left: 0,
      right: 600,
      bottom: 220,
      x: 0,
      y: 0,
      toJSON() {},
    }),
  })

  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub
})

describe('MetricChart', () => {
  it('shows an empty state instead of an empty chart when there is no data', () => {
    render(<MetricChart points={[]} ariaLabel="CPU usage over time" />)

    expect(screen.getByText('No data for this range.')).toBeInTheDocument()
    expect(document.querySelector('.recharts-line-curve')).not.toBeInTheDocument()
  })

  it('exposes an accessible label in both the empty and populated states', () => {
    const { rerender } = render(<MetricChart points={[]} ariaLabel="CPU usage over time" />)
    expect(screen.getByRole('img', { name: 'CPU usage over time' })).toBeInTheDocument()

    rerender(<MetricChart points={POINTS} ariaLabel="CPU usage over time" />)
    expect(screen.getByRole('img', { name: 'CPU usage over time' })).toBeInTheDocument()
  })

  it('renders exactly one line with real geometry, and no empty-state message', () => {
    render(<MetricChart points={POINTS} ariaLabel="CPU usage over time" />)

    const lines = document.querySelectorAll('.recharts-line-curve')
    expect(lines).toHaveLength(1)
    // Not asserting the exact path syntax: `type="monotone"` draws curves
    // ("C" commands) rather than straight segments once there are more than
    // two points, which is an interpolation detail this component does not
    // promise. A non-trivial `d` attribute is what proves the data was
    // actually consumed rather than the line rendering empty.
    expect(lines[0].getAttribute('d')?.length ?? 0).toBeGreaterThan(10)

    expect(screen.queryByText('No data for this range.')).not.toBeInTheDocument()
  })

  it('uses the accent color by default', () => {
    render(<MetricChart points={POINTS} ariaLabel="CPU usage over time" />)

    expect(document.querySelector('.recharts-line-curve')).toHaveAttribute('stroke', 'var(--accent)')
  })

  it('passes a custom color through to the line', () => {
    render(<MetricChart points={POINTS} ariaLabel="CPU usage over time" color="var(--status-down)" />)

    expect(document.querySelector('.recharts-line-curve')).toHaveAttribute('stroke', 'var(--status-down)')
  })

  it('fixes the Y axis to a 0-100% scale with consistent gridlines, the same range every metric uses', () => {
    render(<MetricChart points={POINTS} ariaLabel="CPU usage over time" />)

    // Explicit ticks, not Recharts' default auto count: at typical card
    // heights that heuristic can collapse to showing only "100%", which
    // reads as a broken axis rather than a 0-100% scale.
    for (const tick of ['0%', '25%', '50%', '75%', '100%']) {
      expect(screen.getByText(tick)).toBeInTheDocument()
    }
  })

  it('drops the fixed percent axis for a bytes-per-second series', () => {
    const bytes: SeriesPoint[] = [
      { t: '2026-08-25T10:00:00Z', value: 2048 },
      { t: '2026-08-25T11:00:00Z', value: 4096 },
    ]

    render(<MetricChart points={bytes} unit="bytes_per_sec" ariaLabel="Network throughput over time" />)

    // The line still draws, but no axis tick is a percentage any more.
    expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument()
    expect(screen.queryByText('25%')).not.toBeInTheDocument()
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
  })

  it('drops the fixed percent axis for a count series', () => {
    const counts: SeriesPoint[] = [
      { t: '2026-08-25T10:00:00Z', value: 100 },
      { t: '2026-08-25T11:00:00Z', value: 140 },
    ]

    render(<MetricChart points={counts} unit="count" ariaLabel="Process count over time" />)

    expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument()
    expect(screen.queryByText('25%')).not.toBeInTheDocument()
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
  })

  it('shows a loading skeleton instead of the chart or the empty state when loading', () => {
    render(<MetricChart points={[]} ariaLabel="CPU usage over time" loading />)

    expect(screen.queryByText('No data for this range.')).not.toBeInTheDocument()
    expect(document.querySelector('.recharts-line-curve')).not.toBeInTheDocument()
  })

  it('takes priority over the empty state even if points happen to be populated', () => {
    // Should not be reachable in practice (a page passes loading only before
    // its first fetch resolves, when points is still []) — but loading being
    // checked first, not points.length, is what the component actually
    // guarantees, and that ordering is worth pinning down directly.
    render(<MetricChart points={POINTS} ariaLabel="CPU usage over time" loading />)

    expect(document.querySelector('.recharts-line-curve')).not.toBeInTheDocument()
  })

  it('announces loading to assistive tech via a status region, not a static image label', () => {
    render(<MetricChart points={[]} ariaLabel="CPU usage over time" loading />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading CPU usage over time')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('defaults to not loading, so existing callers are unaffected', () => {
    render(<MetricChart points={POINTS} ariaLabel="CPU usage over time" />)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument()
  })
})
