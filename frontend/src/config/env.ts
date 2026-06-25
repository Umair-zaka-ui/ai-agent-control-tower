/**
 * Centralised, typed access to Vite environment variables.
 * Never read `import.meta.env` directly elsewhere — import from here so the
 * shape is validated and defaulted in one place.
 */

interface AppEnv {
  apiBaseUrl: string
  appName: string
  isDev: boolean
  isProd: boolean
}

function readString(value: string | undefined, fallback: string): string {
  if (value === undefined || value.trim() === '') {
    return fallback
  }
  return value.trim()
}

export const env: AppEnv = {
  apiBaseUrl: readString(import.meta.env.VITE_API_BASE_URL, 'http://localhost:8000'),
  appName: readString(import.meta.env.VITE_APP_NAME, 'AI Agent Control Tower'),
  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD,
}
