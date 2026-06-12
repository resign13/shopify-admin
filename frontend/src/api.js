function resolveApiBase() {
  const envBase = (import.meta.env.VITE_API_BASE_URL || '').trim()
  if (envBase) return envBase

  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    const protocol = window.location.protocol || 'https:'

    if (host === 'admin.gingtto.store') {
      return `${protocol}//api-admin.gingtto.store`
    }

    if (host === 'localhost' || host === '127.0.0.1') {
      return 'http://127.0.0.1:5202'
    }
  }

  return 'http://127.0.0.1:5202'
}

export const API_BASE = resolveApiBase()

import { beginRequestLoading, endRequestLoading } from './loading'

export async function request(path, options = {}) {
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const skipGlobalLoading = Boolean(options.skipGlobalLoading)
  const { skipGlobalLoading: _skipGlobalLoading, ...fetchOptions } = options
  if (!skipGlobalLoading) beginRequestLoading()
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers: {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...(options.headers || {}),
      },
    })
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.message || 'Request failed')
    }
    return data
  } finally {
    if (!skipGlobalLoading) endRequestLoading()
  }
}
