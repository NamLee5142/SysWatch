import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './layout/AppShell'
import { CpuPage } from './pages/CpuPage'
import { DiskPage } from './pages/DiskPage'
import { HistoryPage } from './pages/HistoryPage'
import { MemoryPage } from './pages/MemoryPage'
import { OverviewPage } from './pages/OverviewPage'
import { SystemPage } from './pages/SystemPage'

// Kept apart from App so tests can drive it inside a MemoryRouter and land on
// any path directly, instead of going through the real BrowserRouter and
// window.history.
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="cpu" element={<CpuPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="disk" element={<DiskPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
