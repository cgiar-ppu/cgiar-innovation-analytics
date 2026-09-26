/**
 * @file downloads.ts
 * @module lib
 *
 * L4-06: authenticated download links in chat answers are rendered WITHOUT a
 * token and get the current token only at click time. SSO app tokens live at
 * most 5 minutes and answers are memoised, so a token baked in at render time
 * turned every download link older than ~5 minutes into a 401 page (and left
 * the token in the DOM and in copied links).
 */
import type React from 'react'
import { getAuthToken } from '../stores/auth'

/**
 * Click / middle-click / keyboard handler for an `<a href="/api/files/...">`
 * rendered without a token: swap in the URL with the current token for the
 * browser's default navigation, then put the token-free URL back.
 */
export function withFreshToken(e: React.MouseEvent<HTMLAnchorElement>): void {
  e.stopPropagation()
  const anchor = e.currentTarget
  const base = anchor.getAttribute('href')
  if (!base) return
  const token = getAuthToken()
  if (!token) return
  const sep = base.includes('?') ? '&' : '?'
  anchor.setAttribute('href', `${base}${sep}token=${encodeURIComponent(token)}`)
  // The default action reads href synchronously after the handlers run.
  setTimeout(() => anchor.setAttribute('href', base), 0)
}

/**
 * Raster types that may be shown inline from a same-origin blob: URL. SVG is
 * excluded on purpose: a blob: SVG opened in its own tab would run script
 * with the app's origin (L4-11 / L1-05).
 */
const INLINE_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

/** Fetch an authenticated workspace image as a blob URL (raster types only). */
export async function fetchAuthenticatedImageUrl(url: string, signal?: AbortSignal): Promise<string> {
  const token = getAuthToken()
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    ...(signal ? { signal } : {}),
  })
  if (!res.ok) throw new Error(`GET ${url}: ${res.status}`)
  const blob = await res.blob()
  const type = (blob.type || '').split(';')[0]!.trim().toLowerCase()
  if (!INLINE_IMAGE_TYPES.has(type)) throw new Error(`Not an inline image type: ${type || 'unknown'}`)
  return URL.createObjectURL(blob)
}
