import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Gauge } from './Gauge'

const CIRCUMFERENCE = 2 * Math.PI * 40

describe('Gauge', () => {
  it('renders the rounded percentage', () => {
    render(<Gauge value={42.6} />)

    expect(screen.getByText('43%')).toBeInTheDocument()
  })

  it('renders an optional label', () => {
    render(<Gauge value={50} label="CPU" />)

    expect(screen.getByText('CPU')).toBeInTheDocument()
  })

  it('clamps a value above 100 down to 100%', () => {
    render(<Gauge value={137} />)

    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('clamps a negative value up to 0%', () => {
    render(<Gauge value={-12} />)

    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('draws a full ring at 100%', () => {
    render(<Gauge value={100} />);
    const [, valueCircle] = document.querySelectorAll('circle')

    expect(valueCircle).toHaveAttribute('stroke-dashoffset', '0')
  })

  it('draws an empty ring at 0%', () => {
    render(<Gauge value={0} />)
    const [, valueCircle] = document.querySelectorAll('circle')

    expect(Number(valueCircle.getAttribute('stroke-dashoffset'))).toBeCloseTo(CIRCUMFERENCE)
  })

  it('draws a half-empty ring at 50%', () => {
    render(<Gauge value={50} />)
    const [, valueCircle] = document.querySelectorAll('circle')

    expect(Number(valueCircle.getAttribute('stroke-dashoffset'))).toBeCloseTo(CIRCUMFERENCE / 2)
  })

  it('exposes the reading through an accessible label rather than only the visual text', () => {
    render(<Gauge value={73} label="Memory" />)

    expect(screen.getByRole('img', { name: 'Memory: 73%' })).toBeInTheDocument()
  })

  it('hides the duplicate visual readout from assistive tech', () => {
    render(<Gauge value={73} label="Memory" />)

    const readout = screen.getByText('73%').closest('[aria-hidden]')
    expect(readout).not.toBeNull()
  })
})
