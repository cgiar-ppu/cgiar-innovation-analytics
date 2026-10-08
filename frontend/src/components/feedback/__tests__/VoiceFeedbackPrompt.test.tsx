import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import VoiceFeedbackPrompt from '../VoiceFeedbackPrompt'

describe('VoiceFeedbackPrompt', () => {
  it('is hidden until the guide asks, needs a rating to send, and can be skipped', async () => {
    const onSubmit = vi.fn().mockResolvedValue({ ok: true })
    const onSkip = vi.fn()
    const { container, rerender } = render(<VoiceFeedbackPrompt phase="idle" onSubmit={onSubmit} onSkip={onSkip} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<VoiceFeedbackPrompt phase="asking" onSubmit={onSubmit} onSkip={onSkip} />)
    const user = userEvent.setup()
    expect(screen.getByRole('button', { name: 'Send and end' })).toBeDisabled()
    await user.click(screen.getByRole('radio', { name: '4 of 5' }))
    await user.type(screen.getByLabelText(/One thing that would make it better/), 'Faster answers')
    await user.click(screen.getByRole('button', { name: 'Send and end' }))
    expect(onSubmit).toHaveBeenCalledWith(4, 'Faster answers')
    await user.click(screen.getByRole('button', { name: 'Skip and end' }))
    expect(onSkip).toHaveBeenCalled()
    rerender(<VoiceFeedbackPrompt phase="saved" onSubmit={onSubmit} onSkip={onSkip} />)
    expect(screen.getByRole('status')).toHaveTextContent('Thank you')
  })

  it('shows a save error', async () => {
    const user = userEvent.setup()
    render(<VoiceFeedbackPrompt phase="asking" onSubmit={vi.fn().mockResolvedValue({ ok: false, error: 'Voice session not found' })} onSkip={vi.fn()} />)
    await user.click(screen.getByRole('radio', { name: '2 of 5' }))
    await user.click(screen.getByRole('button', { name: 'Send and end' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Voice session not found')
  })
})
