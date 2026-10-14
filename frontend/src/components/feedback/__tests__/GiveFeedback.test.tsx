/**
 * Global "Give feedback" (MVP test release item 1): a button in the top bar on
 * every page, a form with four categories, free text, an optional PNG/JPEG
 * screenshot (file or paste, max 5 MB) and page/chat context as ids only;
 * hidden when the server reports the feedback kill-switch off.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import GiveFeedbackButton, { pastedImage, screenshotProblem } from '../GiveFeedback'
import { FEEDBACK_CATEGORIES } from '../api'
import { useAppConfigStore } from '../../../stores/appConfig'
import { useAuthStore } from '../../../stores/auth'
import { useChatStore } from '../../../stores/chat'
import { useSessionsStore } from '../../../stores/sessions'
import type { AppConfig, ChatMessage } from '../../../lib/types'

type Call = { url: string; init?: RequestInit }
let calls: Call[]
let reply: { status: number; body: unknown }

const m = (id: string, role: ChatMessage['role']): ChatMessage => ({ id, role, content: id, timestamp: 0 })
const png = (bytes = 10) => new File([new Uint8Array(bytes)], 'shot.png', { type: 'image/png' })

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><GiveFeedbackButton /></MemoryRouter>)
}

beforeEach(() => {
  calls = []
  reply = { status: 200, body: { id: 1, channel: 'general', category: 'stuck', has_attachment: false } }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'Content-Type': 'application/json' } })
  }))
  URL.createObjectURL = vi.fn(() => 'blob:preview'); URL.revokeObjectURL = vi.fn()
  useAuthStore.setState({ token: 'jwt', user: { userId: 'sso:alice', email: 'a@cgiar.org', name: 'Alice', role: 'researcher' } } as never)
  useAppConfigStore.setState({ config: { feedback_enabled: true } as AppConfig })
  useSessionsStore.setState({ activeSessionId: 's1' } as never)
  useChatStore.setState({ messages: [m('u1', 'user'), m('a1', 'assistant'), m('r1', 'result'), m('u2', 'user'), m('a2', 'assistant'), m('r2', 'result')] })
})

describe('Give feedback button', () => {
  it('renders in the top bar and opens a form with the four categories', async () => {
    const user = userEvent.setup()
    renderAt('/')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    const dialog = screen.getByRole('dialog', { name: 'Give feedback' })
    expect(dialog).toBeInTheDocument()
    const radios = screen.getAllByRole('radio')
    expect(radios.map(r => (r as HTMLInputElement).value)).toEqual(['stuck', 'wrong_result', 'inappropriate_inaccurate', 'other'])
    expect(FEEDBACK_CATEGORIES.map(c => c.label)).toEqual(["I'm stuck", 'This result looks wrong', 'Inappropriate or inaccurate', 'Other'])
    expect(radios[0]).toHaveFocus()
    expect(calls).toEqual([])
  })

  it('is hidden when the server has feedback switched off', () => {
    useAppConfigStore.setState({ config: { feedback_enabled: false } as AppConfig })
    renderAt('/')
    expect(screen.queryByRole('button', { name: 'Give feedback' })).toBeNull()
  })

  it('submits category, text, page and the chat context (ids only) as multipart with the token', async () => {
    const user = userEvent.setup()
    renderAt('/chat')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    expect(screen.getByText(/the id of this chat and of its latest answer \(not the chat text\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /This result looks wrong/ }))
    await user.type(screen.getByLabelText('What happened?'), 'The 2025 total is too low')
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Your feedback was sent')
    expect(calls).toHaveLength(1)
    const { url, init } = calls[0]!
    expect(url).toBe('/api/feedback/general')
    expect(init?.method).toBe('POST')
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer jwt')
    expect((init?.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    const body = init?.body as FormData
    expect(body.get('category')).toBe('wrong_result')
    expect(body.get('comment')).toBe('The 2025 total is too low')
    expect(body.get('page')).toBe('/chat')
    expect(body.get('chat_id')).toBe('s1')
    expect(body.get('answer_id')).toBe('r2')
    expect(body.get('screenshot')).toBeNull()
  })

  it('outside a chat it sends no chat context', async () => {
    const user = userEvent.setup()
    renderAt('/settings')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    await user.click(screen.getByRole('radio', { name: /I'm stuck/ }))
    await user.type(screen.getByLabelText('What happened?'), 'Where is the export?')
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    await screen.findByRole('status')
    const body = calls[0]!.init?.body as FormData
    expect(body.get('page')).toBe('/settings')
    expect(body.get('chat_id')).toBeNull()
    expect(body.get('answer_id')).toBeNull()
  })

  it('asks for a category and for text or a screenshot before sending', async () => {
    const user = userEvent.setup()
    renderAt('/')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Please choose what kind of feedback this is.')
    await user.click(screen.getByRole('radio', { name: /Other/ }))
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(screen.getByRole('alert')).toHaveTextContent('describe what happened or add a screenshot')
    expect(calls).toEqual([])
  })

  it('attaches a chosen screenshot and rejects wrong types and files over 5 MB', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderAt('/')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    const input = screen.getByTestId('feedback-screenshot-input')
    await user.upload(input, new File(['x'], 'a.gif', { type: 'image/gif' }))
    expect(screen.getByRole('alert')).toHaveTextContent('PNG or JPEG')
    await user.upload(input, png(5 * 1024 * 1024 + 1))
    expect(screen.getByRole('alert')).toHaveTextContent('larger than 5 MB')
    await user.upload(input, png())
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByAltText('Screenshot preview')).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /Other/ }))
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    await screen.findByRole('status')
    const sent = (calls[0]!.init?.body as FormData).get('screenshot') as File
    expect(sent).toBeInstanceOf(File)
    expect(sent.name).toBe('screenshot.png')
  })

  it('accepts a pasted image', async () => {
    const user = userEvent.setup()
    renderAt('/')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    const file = png()
    fireEvent.paste(screen.getByLabelText('What happened?'), {
      clipboardData: { items: [{ kind: 'file', type: 'image/png', getAsFile: () => file }] },
    })
    expect(screen.getByAltText('Screenshot preview')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(screen.queryByAltText('Screenshot preview')).toBeNull()
  })

  it('shows the server error and closes with Escape', async () => {
    reply = { status: 413, body: { detail: 'The screenshot is larger than 5 MB' } }
    const user = userEvent.setup()
    renderAt('/')
    await user.click(screen.getByRole('button', { name: 'Give feedback' }))
    await user.click(screen.getByRole('radio', { name: /Other/ }))
    await user.type(screen.getByLabelText('What happened?'), 'x')
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('larger than 5 MB'))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('screenshot helpers', () => {
  it('checks type and size', () => {
    expect(screenshotProblem(png())).toBe('')
    expect(screenshotProblem(new File(['x'], 'a.jpg', { type: 'image/jpeg' }))).toBe('')
    expect(screenshotProblem(new File(['<svg/>'], 'a.svg', { type: 'image/svg+xml' }))).toMatch(/PNG or JPEG/)
  })
  it('finds the first image on the clipboard and ignores text', () => {
    const file = png()
    expect(pastedImage({ clipboardData: { items: [{ kind: 'string', type: 'text/plain' }, { kind: 'file', type: 'image/png', getAsFile: () => file }] } } as never)).toBe(file)
    expect(pastedImage({ clipboardData: { items: [{ kind: 'string', type: 'text/plain' }] } } as never)).toBeNull()
  })
})
