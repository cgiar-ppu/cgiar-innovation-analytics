/**
 * Tests for filePathUtils (2026-07-20 fix): download URLs now carry a
 * `?token=` query param (the files API requires auth), and workspace-prefixed
 * anchor hrefs are rewritten to the authenticated download endpoint.
 */

import { describe, it, expect } from 'vitest'
import {
  buildDownloadUrl,
  extractRelativePath,
  resolveWorkspaceHref,
  isWorkspaceHref,
  parseFilePathsInText,
} from '../filePathUtils'

describe('buildDownloadUrl', () => {
  it('builds a plain download URL with no token', () => {
    expect(buildDownloadUrl('outputs/report.html')).toBe('/api/files/outputs/report.html')
  })

  it('appends ?token= when a token is supplied', () => {
    expect(buildDownloadUrl('outputs/report.html', 'jwt-abc')).toBe(
      '/api/files/outputs/report.html?token=jwt-abc',
    )
  })

  it('omits the token param when token is null/undefined', () => {
    expect(buildDownloadUrl('outputs/report.html', null)).toBe('/api/files/outputs/report.html')
    expect(buildDownloadUrl('outputs/report.html', undefined)).toBe('/api/files/outputs/report.html')
  })

  it('URL-encodes both path segments and the token', () => {
    const url = buildDownloadUrl('outputs/my report.html', 'a.b/c+d')
    expect(url).toBe('/api/files/outputs/my%20report.html?token=a.b%2Fc%2Bd')
  })
})

describe('isWorkspaceHref / resolveWorkspaceHref', () => {
  it('recognizes all four workspace prefix formats', () => {
    expect(isWorkspaceHref('/workspace/outputs/f.docx')).toBe(true)
    expect(isWorkspaceHref('/Users/smithai/workspace/outputs/f.docx')).toBe(true)
    expect(isWorkspaceHref('/home/ec2-user/workspace/outputs/f.docx')).toBe(true)
    expect(isWorkspaceHref('~/workspace/outputs/f.docx')).toBe(true)
  })

  it('does not treat external URLs as workspace hrefs', () => {
    expect(isWorkspaceHref('https://reporting.cgiar.org/result/123')).toBe(false)
    expect(isWorkspaceHref('http://example.com/workspace-lookalike/x')).toBe(false)
    expect(isWorkspaceHref('')).toBe(false)
  })

  it('rewrites a raw workspace path href to the authenticated download endpoint', () => {
    const resolved = resolveWorkspaceHref('/workspace/outputs/report.docx', 'jwt-xyz')
    expect(resolved).toBe('/api/files/outputs/report.docx?token=jwt-xyz')
  })

  it('rewrites the macOS absolute-path form too', () => {
    const resolved = resolveWorkspaceHref(
      '/Users/smithai/workspace/outputs/f.docx',
      'jwt-xyz',
    )
    expect(resolved).toBe('/api/files/outputs/f.docx?token=jwt-xyz')
  })

  it('passes external hrefs through unchanged', () => {
    const href = 'https://reporting.cgiar.org/result/123'
    expect(resolveWorkspaceHref(href, 'jwt-xyz')).toBe(href)
  })

  it('resolves without a token when none is supplied (dev-bypass mode)', () => {
    expect(resolveWorkspaceHref('/workspace/outputs/report.docx')).toBe(
      '/api/files/outputs/report.docx',
    )
  })

  it('strips a leading file:// scheme before resolving', () => {
    expect(resolveWorkspaceHref('file:///workspace/outputs/report.docx', 't')).toBe(
      '/api/files/outputs/report.docx?token=t',
    )
  })
})

// Sanity check that the underlying primitives this fix builds on still work
// as documented (regression guard, not new behavior).
describe('extractRelativePath / parseFilePathsInText (unchanged behavior)', () => {
  it('extracts the relative path from all workspace prefix formats', () => {
    expect(extractRelativePath('/workspace/outputs/chart.png')).toBe('outputs/chart.png')
    expect(extractRelativePath('/Users/smithai/workspace/outputs/chart.png')).toBe(
      'outputs/chart.png',
    )
  })

  it('parses plain-text workspace paths into filepath segments', () => {
    const segments = parseFilePathsInText('See /workspace/outputs/chart.png for details')
    expect(segments).toEqual([
      { type: 'text', value: 'See ' },
      {
        type: 'filepath',
        value: '/workspace/outputs/chart.png',
        relativePath: 'outputs/chart.png',
        filename: 'chart.png',
      },
      { type: 'text', value: ' for details' },
    ])
  })
})
