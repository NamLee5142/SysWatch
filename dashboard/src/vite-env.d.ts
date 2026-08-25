/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Backend origin to call directly. Unset in development, where the Vite
  // proxy (vite.config.ts) makes '/api' work without one; a production build
  // has no such proxy, so a deployment must set this to the backend's origin.
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
