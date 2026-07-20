/**
 * Tests for the markdown `a` (anchor) override (2026-07-20 fix).
 *
 * Root cause: agent replies containing a markdown link to a workspace path
 * (e.g. `[report](/workspace/outputs/report.docx)`) rendered as a RAW
 * `<a href="/workspace/outputs/report.docx">` — clicking it navigated the
 * browser to a path matched by neither a frontend route nor an API route,
 * so the SPA catch-all served `index.html` (200, blank/broken page) instead
 * of downloading the file. `MarkdownAnchor` rewrites workspace-prefixed
 * hrefs to the authenticated `/api/files/...` download endpoint; everything
 * else passes through unchanged.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReactMarkdown from 'react-markdown'
import { REMARK_PLUGINS, ASSISTANT_MD_COMPONENTS, STREAMING_MD_COMPONENTS } from '../markdownComponents'
import { useAuthStore } from '../../../stores/auth'

function renderMarkdown(md: string, components = ASSISTANT_MD_COMPONENTS) {
  return render(
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
      {md}
    </ReactMarkdown>,
  )
}

describe('MarkdownAnchor (ASSISTANT_MD_COMPONENTS)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-test-token', authRequired: true })
  })

  it('rewrites a markdown link to a /workspace/... path into a working download link', () => {
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    const link = screen.getByRole('link', { name: 'my report' })
    expect(link).toHaveAttribute(
      'href',
      '/api/files/outputs/report.docx?token=jwt-test-token',
    )
  })

  it('rewrites the macOS absolute-path workspace form too', () => {
    renderMarkdown('[chart](/Users/smithai/workspace/outputs/chart.png)')
    const link = screen.getByRole('link', { name: 'chart' })
    expect(link).toHaveAttribute(
      'href',
      '/api/files/outputs/chart.png?token=jwt-test-token',
    )
  })

  it('adds download + new-tab attributes only for workspace-file links', () => {
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    const link = screen.getByRole('link', { name: 'my report' })
    expect(link).toHaveAttribute('download')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('leaves external / citation links unchanged (no rewrite, no forced target)', () => {
    renderMarkdown('[R1234](https://reporting.cgiar.org/result-details/1234)')
    const link = screen.getByRole('link', { name: 'R1234' })
    expect(link).toHaveAttribute('href', 'https://reporting.cgiar.org/result-details/1234')
    expect(link).not.toHaveAttribute('download')
  })

  it('resolves without a token in dev-bypass mode (no token in store)', () => {
    useAuthStore.setState({ token: null, authRequired: false })
    renderMarkdown('[my report](/workspace/outputs/report.docx)')
    const link = screen.getByRole('link', { name: 'my report' })
    expect(link).toHaveAttribute('href', '/api/files/outputs/report.docx')
  })
})

describe('MarkdownAnchor (STREAMING_MD_COMPONENTS)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-stream-token', authRequired: true })
  })

  it('also rewrites workspace links while a message is still streaming', () => {
    renderMarkdown('[draft](/workspace/outputs/draft.md)', STREAMING_MD_COMPONENTS)
    const link = screen.getByRole('link', { name: 'draft' })
    expect(link).toHaveAttribute(
      'href',
      '/api/files/outputs/draft.md?token=jwt-stream-token',
    )
  })
})

describe('MarkdownImage (token propagation, regression guard)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ token: 'jwt-img-token', authRequired: true })
  })

  it('appends the token to inline workspace image srcs too', () => {
    renderMarkdown('![chart](/workspace/outputs/chart.png)')
    const img = screen.getByRole('img', { name: 'chart' })
    expect(img).toHaveAttribute('src', '/api/files/outputs/chart.png?token=jwt-img-token')
  })
})
