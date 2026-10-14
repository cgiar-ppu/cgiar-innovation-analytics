/** Invitation manager: cohort + expiry on single and bulk invitations; links shown to the admin only. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import InvitationManager, { parseInvitees } from '../InvitationManager'
import { useAuthStore } from '../../../stores/auth'

let posts: { url: string; body: Record<string, unknown> }[]
let accounts: unknown[]
beforeEach(() => {
  posts = []
  accounts = [{ email: 'old@worldbank.example', name: 'Old Tester', enabled: 1, activated: 1, expires_at: null, cohort: 'WB TTLs Oct-2026' }]
  useAuthStore.setState({ token: 'jwt', user: { userId: 'a', email: 'a@x', name: 'A', role: 'admin' } } as never)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      posts.push({ url, body })
      if (url.endsWith('/bulk')) return Response.json({ cohort: body.cohort, expires_in_days: body.expires_in_days,
        invitations: body.invitees.slice(0, 2).map((i: { email: string; name: string }, n: number) => ({ ...i, invitation_url: `https://ia.test/#invite=tok${n}` })),
        errors: [{ email: 'staff@cgiar.org', error: 'CGIAR staff should use CGIAR SSO' }] })
      if (url.endsWith('/revoke-cohort')) return Response.json({ cohort: body.cohort, revoked: 1 })
      return Response.json({ invitation_url: 'https://ia.test/#invite=single', expires_in_days: body.expires_in_days, cohort: body.cohort })
    }
    return Response.json(accounts)
  }))
})

describe('parseInvitees', () => {
  it('reads Name <email>, email + name in either order, and bare emails; reports lines without an email', () => {
    const { invitees, problems } = parseInvitees('Jane Doe <jane.doe@worldbank.example>\njohn.smith@fcdo.example, John Smith\nAna Ruiz; ana@wb.example\nmary-jo.lee@wb.example\n\njust a name')
    expect(invitees).toEqual([
      { email: 'jane.doe@worldbank.example', name: 'Jane Doe' },
      { email: 'john.smith@fcdo.example', name: 'John Smith' },
      { email: 'ana@wb.example', name: 'Ana Ruiz' },
      { email: 'mary-jo.lee@wb.example', name: 'Mary Jo Lee' },
    ])
    expect(problems).toEqual(['just a name'])
  })
})

describe('InvitationManager', () => {
  it('creates a single invitation with a cohort and expiry and shows the link with a no-email note', async () => {
    const user = userEvent.setup()
    render(<InvitationManager />)
    await user.type(await screen.findByLabelText('Name'), 'Ext Researcher')
    await user.type(screen.getByLabelText('External email'), 'ext@worldbank.example')
    await user.type(screen.getByLabelText('Test cohort (optional)'), 'WB TTLs Oct-2026')
    await user.selectOptions(screen.getByLabelText('Link valid for'), '14')
    await user.click(screen.getByRole('button', { name: 'Create invitation link' }))
    // New invitations default to the external partner view (no budget/financial data).
    expect(screen.getByLabelText('Access level')).toHaveValue('external')
    await waitFor(() => expect(posts[0]).toEqual({ url: '/api/auth/invitations', body: { email: 'ext@worldbank.example', name: 'Ext Researcher', cohort: 'WB TTLs Oct-2026', expires_in_days: 14, role: 'external' } }))
    expect(screen.getByLabelText('Invitation link')).toHaveValue('https://ia.test/#invite=single')
    expect(screen.getByText(/expires in 14 days and can be used once\. No email has been sent\./)).toBeInTheDocument()
  })

  it('creates links for a test group, lists each with a copy button, and reports skipped people', async () => {
    const user = userEvent.setup()
    render(<InvitationManager />)
    await user.click(await screen.findByRole('tab', { name: 'Several people (test group)' }))
    await user.type(screen.getByLabelText(/People to invite/), 'Jane Doe <jane@worldbank.example>{enter}john@fcdo.example, John{enter}Staff <staff@cgiar.org>')
    await user.type(screen.getByLabelText('Test cohort (optional)'), 'WB TTLs Oct-2026')
    await user.selectOptions(screen.getByLabelText('Access level'), 'researcher')
    await user.click(screen.getByRole('button', { name: 'Create 3 links' }))
    await waitFor(() => expect(posts[0]!.url).toBe('/api/auth/invitations/bulk'))
    expect(posts[0]!.body).toEqual({ cohort: 'WB TTLs Oct-2026', expires_in_days: 7, role: 'researcher', invitees: [
      { email: 'jane@worldbank.example', name: 'Jane Doe' }, { email: 'john@fcdo.example', name: 'John' }, { email: 'staff@cgiar.org', name: 'Staff' }] })
    const links = await screen.findByTestId('bulk-links')
    expect(links).toHaveTextContent('2 links for "WB TTLs Oct-2026"')
    expect(screen.getByLabelText('Invitation link for jane@worldbank.example')).toHaveValue('https://ia.test/#invite=tok0')
    expect(screen.getAllByRole('button', { name: /Copy link/ })).toHaveLength(2)
    expect(screen.getByRole('alert')).toHaveTextContent('staff@cgiar.org: CGIAR staff should use CGIAR SSO')
  })

  it('shows cohort labels and can end a test round by revoking a cohort after confirmation', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<InvitationManager />)
    expect(await screen.findByText('Old Tester')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/Show cohort/), 'WB TTLs Oct-2026')
    await user.click(screen.getByRole('button', { name: /End test round/ }))
    await waitFor(() => expect(posts.slice(-1)[0]!).toEqual({ url: '/api/auth/invitations/revoke-cohort', body: { cohort: 'WB TTLs Oct-2026' } }))
    expect(await screen.findByRole('status')).toHaveTextContent('Revoked 1 account in "WB TTLs Oct-2026".')
  })

  it('shows each account\'s access level and can switch it after confirmation', async () => {
    accounts = [
      { email: 'old@worldbank.example', name: 'Old Tester', enabled: 1, activated: 1, expires_at: null, cohort: 'WB TTLs Oct-2026' },
      { email: 'partner@fcdo.example', name: 'Partner', enabled: 1, activated: 0, expires_at: null, cohort: 'Partner pilot', role: 'external' },
    ]
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<InvitationManager />)
    expect((await screen.findAllByTestId('account-role')).find(e => e.dataset.accountEmail === 'old@worldbank.example')).toHaveTextContent('Researcher')   // pre-role accounts
    expect(screen.getAllByTestId('account-role').find(e => e.dataset.accountEmail === 'partner@fcdo.example')).toHaveTextContent('External')
    await user.click(screen.getByRole('button', { name: 'Make external partner' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/sign in again/))
    await waitFor(() => expect(posts.slice(-1)[0]!).toEqual({ url: '/api/auth/invitations/role', body: { email: 'old@worldbank.example', role: 'external' } }))
    await user.click(screen.getByRole('button', { name: 'Give full data access' }))
    await waitFor(() => expect(posts.slice(-1)[0]!).toEqual({ url: '/api/auth/invitations/role', body: { email: 'partner@fcdo.example', role: 'researcher' } }))
  })

  it('reissue keeps the account\'s access level', async () => {
    accounts = [{ email: 'partner@fcdo.example', name: 'Partner', enabled: 1, activated: 1, expires_at: null, cohort: '', role: 'researcher' }]
    const user = userEvent.setup()
    render(<InvitationManager />)
    await user.click(await screen.findByRole('button', { name: 'Reissue / reset' }))
    expect(screen.getByLabelText('Access level')).toHaveValue('researcher')
    await user.click(screen.getByRole('button', { name: 'Create invitation link' }))
    await waitFor(() => expect(posts[0]!.body).toMatchObject({ email: 'partner@fcdo.example', role: 'researcher' }))
  })

  it('is not rendered for non-admins', () => {
    useAuthStore.setState({ user: { userId: 'r', email: 'r@x', name: 'R', role: 'researcher' } } as never)
    const { container } = render(<InvitationManager />)
    expect(container).toBeEmptyDOMElement()
  })
})
