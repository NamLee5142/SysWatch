import { Navigate, Route, Routes } from 'react-router-dom'

import { LoginRoute } from './auth/LoginRoute'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { SelectedHostProvider } from './hosts/SelectedHostProvider'
import { AppShell } from './layout/AppShell'
import { AlertsPage } from './pages/AlertsPage'
import { CpuPage } from './pages/CpuPage'
import { DiskPage } from './pages/DiskPage'
import { HistoryPage } from './pages/HistoryPage'
import { MemoryPage } from './pages/MemoryPage'
import { NetworkPage } from './pages/NetworkPage'
import { OverviewPage } from './pages/OverviewPage'
import { ProcessPage } from './pages/ProcessPage'
import { SystemPage } from './pages/SystemPage'

// Kept apart from App so tests can drive it inside a MemoryRouter and land on
// any path directly, instead of going through the real BrowserRouter and
// window.history.
export function AppRoutes() {
  return (
    <Routes>
      {/* Outside the shell and outside ProtectedRoute: the shell polls
          endpoints that now need a session, so a login page inside it
          would fire requests it is guaranteed to get 401s for. */}
      <Route path="/login" element={<LoginRoute />} />
      <Route element={<ProtectedRoute />}>
        {/* Inside ProtectedRoute for the same reason the shell is: it polls
            /hosts, which needs a session. Outside AppShell because the shell's
            own header reads the selection. */}
        <Route
          element={
            <SelectedHostProvider>
              <AppShell />
            </SelectedHostProvider>
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="cpu" element={<CpuPage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="disk" element={<DiskPage />} />
          <Route path="processes" element={<ProcessPage />} />
          <Route path="network" element={<NetworkPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
