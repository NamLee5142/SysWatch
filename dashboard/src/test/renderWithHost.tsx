import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import { vi } from 'vitest'
import type { ReactNode } from 'react'

import type { Host } from '../api/types'
import { SelectedHostContext, type SelectedHostValue } from '../hosts/SelectedHostContext'

export const DEFAULT_TEST_HOST = 'devbox'

interface Options extends RenderOptions {
  hosts?: Host[]
  /** Explicit null renders the no-host-has-reported state. */
  hostName?: string | null
  select?: SelectedHostValue['select']
}

/**
 * Render a page with a host selected.
 *
 * Pages read the selection from context, so they cannot be rendered bare any
 * more. The value is supplied directly rather than by mounting the real
 * provider: these tests are about what a page does with a given host, and
 * going through the provider would mean stubbing /hosts in every file to
 * arrange it. SelectedHostProvider has its own tests for how the selection is
 * arrived at.
 *
 * Deliberately separate from renderWithAuth. A metric page needs a host, not
 * an identity, and giving it both would hide which one it actually depends on.
 */
export function renderWithHost(ui: ReactNode, options: Options = {}): RenderResult {
  const {
    hosts = [
      { hostName: DEFAULT_TEST_HOST, lastCollectedAt: '2026-09-08T10:00:00Z', snapshotCount: 1 },
    ],
    select = vi.fn(),
    ...rest
  } = options
  const hostName = 'hostName' in options ? options.hostName : (hosts[0]?.hostName ?? null)

  const value: SelectedHostValue = {
    hosts,
    hostName: hostName ?? null,
    loading: false,
    select,
  }

  return render(
    <SelectedHostContext.Provider value={value}>{ui}</SelectedHostContext.Provider>,
    rest,
  )
}
