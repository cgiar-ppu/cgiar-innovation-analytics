/**
 * Tests for the markdown `a` / `img` overrides.
 *
 * 2026-07-20: workspace-path links (e.g. `[report](/workspace/outputs/report.docx)`)
 * are rewritten to the authenticated `/api/files/...` download endpoint.
 *
 * 2026-09-26 (L4-06): the token is NOT baked into the rendered href any more.
 * SSO app tokens live at most 5 minutes and answers are memoised, so links in
 * older answers returned 401. The href is token-free; the current token is
 * added at click time. Workspace images are fetched with an Authorization
 * header. External / PRMS citation links open in a new tab (L4-14).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ReactMarkdown from 'react-markdown'
import { REMARK_PLUGINS, ASSISTANT_MD_COMPONENTS, STREAMING_MD_COMPONENTS } from '../markdownComponents'
import { FileDownloadLink } from '../FileDownloadLink'
import { useAuthStore } from '../../../stores/auth'

function renderMarkdown(md: string, components = ASSISTANT_MD_COMPONENTS) {
  return render(
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
      {md}
    </ReactMarkdown>,
  )
}

/**
 * Click an anchor and return the href it carries while the browser's default
 * action runs (the handler swaps the token in synchronously and restores the
 * token-free href on the next tick). jsdom cannot navigate, so the default
 * action is prevented at the target.
 */
function clickAndReadHref(link: HTMLElement, kind: 'click' | 'auxClick' = 'click'): string {
  link.addEventListener('click', (e) => e.preventDefault())
  link.addEventListener('auxclick', (e) => e.preventDefault())
  if (kind === 'click') fireEvent.click(link)
  else fireEvent(link, new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 }))
  return link.getAttribute('href') ?? ''
}

describe('MarkdownAnchor (ASSISTANT_MD_COMPONENTS)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-test-token', authRequired: true })
  })

  it('rewrites a /workspace/... link into a token-free download link', () => {
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    const link = screen.getByRole('link', { name: 'my report' })
    expect(link).toHaveAttribute('href', '/api/files/outputs/report.docx')
    expect(link.getAttribute('href')).not.toContain('token')
  })

  it('rewrites the macOS absolute-path workspace form too', () => {
    renderMarkdown('[chart](/Users/smithai/workspace/outputs/chart.png)')
    expect(screen.getByRole('link', { name: 'chart' })).toHaveAttribute('href', '/api/files/outputs/chart.png')
  })

  it('adds the CURRENT token at click time, not the one from render time', () => {
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    // The SSO refresh swapped the token after the answer was rendered.
    useAuthStore.setState({ token: 'fresh-token' })
    const link = screen.getByRole('link', { name: 'my report' })
    expect(clickAndReadHref(link)).toBe('/api/files/outputs/report.docx?token=fresh-token')
  })

  it('puts the token-free href back after the click', async () => {
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    const link = screen.getByRole('link', { name: 'my report' })
    clickAndReadHref(link)
    await waitFor(() => expect(link).toHaveAttribute('href', '/api/files/outputs/report.docx'))
  })

  it('adds download + new-tab attributes for workspace-file links', () => {
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    const link = screen.getByRole('link', { name: 'my report' })
    expect(link).toHaveAttribute('download')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('opens external / citation links in a new tab without rewriting them (L4-14)', () => {
    renderMarkdown('[R1234](https://reporting.cgiar.org/result-details/1234)')
    const link = screen.getByRole('link', { name: 'R1234' })
    expect(link).toHaveAttribute('href', 'https://reporting.cgiar.org/result-details/1234')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).not.toHaveAttribute('download')
  })

  it('leaves the href token-free on click in dev-bypass mode (no token)', () => {
    useAuthStore.setState({ token: null, authRequired: false })
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    expect(clickAndReadHref(screen.getByRole('link', { name: 'my report' }))).toBe('/api/files/outputs/report.docx')
  })
})

describe('pseudo-scheme download links (QA-4 D4)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-test-token', authRequired: true })
  })

  it('a sandbox:/workspace/... link becomes a working download link', () => {
    renderMarkdown('[Kenya_list.xlsx](sandbox:/workspace/outputs/u/abc/0123/Kenya_list.xlsx)')
    const link = screen.getByRole('link', { name: 'Kenya_list.xlsx' })
    expect(link).toHaveAttribute('href', '/api/files/outputs/u/abc/0123/Kenya_list.xlsx')
    expect(link).toHaveAttribute('download')
  })

  it('file:///workspace/... works too', () => {
    renderMarkdown('[report](file:///workspace/outputs/report.docx)')
    expect(screen.getByRole('link', { name: 'report' })).toHaveAttribute('href', '/api/files/outputs/report.docx')
  })

  it('a link whose text is the server path shows only the file name', () => {
    renderMarkdown('[/workspace/outputs/u/abc/0123/brief.docx](sandbox:/workspace/outputs/u/abc/0123/brief.docx)')
    const link = screen.getByRole('link', { name: 'brief.docx' })
    expect(link.textContent).toBe('brief.docx')
    expect(link).toHaveAttribute('href', '/api/files/outputs/u/abc/0123/brief.docx')
  })

  it('a bare sandbox: path in text becomes a download chip without the prefix', () => {
    const { container } = renderMarkdown('Download: sandbox:/workspace/outputs/u/abc/0123/list.csv')
    expect(container.textContent).not.toContain('sandbox:')
    const link = container.querySelector('a[href="/api/files/outputs/u/abc/0123/list.csv"]')
    expect(link).not.toBeNull()
  })

  it('never touches real URLs', () => {
    renderMarkdown('[site](https://example.org/sandbox:/workspace/x)')
    expect(screen.getByRole('link', { name: 'site' })).toHaveAttribute('href', 'https://example.org/sandbox:/workspace/x')
  })
})

describe('MarkdownAnchor (STREAMING_MD_COMPONENTS)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-stream-token', authRequired: true })
  })

  it('also rewrites workspace links while a message is still streaming', () => {
    renderMarkdown('[draft](/workspace/outputs/draft.md)', STREAMING_MD_COMPONENTS)
    expect(screen.getByRole('link', { name: 'draft' })).toHaveAttribute('href', '/api/files/outputs/draft.md')
  })
})

describe('FileDownloadLink (L4-06)', () => {
  beforeEach(() => useAuthStore.setState({ token: 'render-time-token', authRequired: true }))

  it('renders without a token and downloads with the token current at click time', () => {
    render(<FileDownloadLink relativePath="outputs/u/abc/x/report.docx" filename="report.docx" fullPath="/workspace/outputs/u/abc/x/report.docx" />)
    const link = screen.getByRole('link')
    expect(link.getAttribute('href')).toBe('/api/files/outputs/u/abc/x/report.docx')
    useAuthStore.setState({ token: 'click-time-token' })
    expect(clickAndReadHref(link)).toBe('/api/files/outputs/u/abc/x/report.docx?token=click-time-token')
  })

  it('middle-click (open in new tab) also gets the fresh token', () => {
    render(<FileDownloadLink relativePath="outputs/a.csv" filename="a.csv" fullPath="/workspace/outputs/a.csv" />)
    useAuthStore.setState({ token: 'aux-token' })
    expect(clickAndReadHref(screen.getByRole('link'), 'auxClick')).toBe('/api/files/outputs/a.csv?token=aux-token')
  })
})

describe('MarkdownImage (authenticated fetch, L4-06)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-img-token', authRequired: true })
    URL.createObjectURL = vi.fn(() => 'blob:chart')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('fetches workspace images with the current token in a header, never in src', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['png'], { type: 'image/png' }) })
    vi.stubGlobal('fetch', fetcher)
    renderMarkdown('![chart](/workspace/outputs/chart.png)')
    const img = await screen.findByRole('img', { name: 'chart' })
    expect(img).toHaveAttribute('src', 'blob:chart')
    expect(fetcher).toHaveBeenCalledWith('/api/files/outputs/chart.png', expect.objectContaining({
      headers: { Authorization: 'Bearer jwt-img-token' },
    }))
  })

  it('says the image is unavailable instead of showing a broken image', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    renderMarkdown('![chart](/workspace/outputs/chart.png)')
    expect(await screen.findByText(/image unavailable/)).toBeInTheDocument()
  })

  it('never inlines an SVG from a same-origin blob (script would run as the app)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['<svg/>'], { type: 'image/svg+xml' }) }))
    renderMarkdown('![diagram](/workspace/outputs/diagram.svg)')
    expect(await screen.findByText(/image unavailable/)).toBeInTheDocument()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('passes external image URLs through unchanged', () => {
    renderMarkdown('![logo](https://www.cgiar.org/logo.png)')
    expect(screen.getByRole('img', { name: 'logo' })).toHaveAttribute('src', 'https://www.cgiar.org/logo.png')
  })
})
