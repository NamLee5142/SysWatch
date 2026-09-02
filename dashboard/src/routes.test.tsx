import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { AppRoutes } from './routes'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

describe('AppRoutes', () => {
  it.each([
    ['/', 'Overview'],
    ['/cpu', 'CPU'],
    ['/memory', 'Memory'],
    ['/disk', 'Disk'],
    ['/processes', 'Processes'],
    ['/system', 'System'],
    ['/history', 'History'],
  ])('renders the %s page at %s', (path, heading) => {
    renderAt(path)

    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it('redirects an unknown path back to Overview', () => {
    renderAt('/no-such-page')

    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('lists every section in the sidebar', () => {
    renderAt('/')

    const nav = screen.getByRole('navigation', { name: 'Sections' })
    const labels = ['Overview', 'CPU', 'Memory', 'Disk', 'Processes', 'System', 'History']

    for (const label of labels) {
      expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('marks only the current section as the active link', () => {
    renderAt('/cpu')

    expect(screen.getByRole('link', { name: 'CPU' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  })

  it('does not mark Overview active on every other page', () => {
    renderAt('/history')

    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  })

  it('navigates between sections without a full page reload', async () => {
    const user = userEvent.setup()
    renderAt('/')

    await user.click(screen.getByRole('link', { name: 'Memory' }))

    expect(screen.getByRole('heading', { name: 'Memory' })).toBeInTheDocument()
  })
})
