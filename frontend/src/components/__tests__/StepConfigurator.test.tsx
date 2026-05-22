/**
 * Tests for StepConfigurator (components/workflows/StepConfigurator.tsx).
 *
 * The sub-panels are collapsed by default, so tests that need to inspect
 * inner content first click the header button to expand the panel.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StepConfigurator from '../workflows/StepConfigurator'
import type { StepConfig } from '../workflows/StepConfigurator'

const availableAgents = [
  { id: 'orchestrator', name: 'Orchestrator (Full Team)' },
  { id: 'data_analysis', name: 'Data Analysis' },
  { id: 'visualization_reporting', name: 'Visualization & Reporting' },
]

describe('StepConfigurator', () => {
  // -----------------------------------------------------------------------
  // test_renders_nothing_when_empty
  // -----------------------------------------------------------------------
  it('test_renders_nothing_when_empty', () => {
    const { container } = render(
      <StepConfigurator
        steps={[]}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  // -----------------------------------------------------------------------
  // test_renders_step_panels
  // -----------------------------------------------------------------------
  it('test_renders_step_panels', () => {
    const steps: StepConfig[] = [
      { agent_id: 'data_analysis' },
      { agent_id: 'visualization_reporting' },
    ]

    render(
      <StepConfigurator
        steps={steps}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )

    // Two "Step N options" buttons should appear
    expect(screen.getByText('Step 1 options')).toBeInTheDocument()
    expect(screen.getByText('Step 2 options')).toBeInTheDocument()
  })

  it('test_renders_correct_number_of_panels', () => {
    const steps: StepConfig[] = [
      { agent_id: 'data_analysis' },
      { agent_id: 'visualization_reporting' },
      { agent_id: 'orchestrator' },
    ]

    render(
      <StepConfigurator
        steps={steps}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )

    expect(screen.getByText('Step 1 options')).toBeInTheDocument()
    expect(screen.getByText('Step 2 options')).toBeInTheDocument()
    expect(screen.getByText('Step 3 options')).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_orchestrator_shows_subagent_checkboxes
  // -----------------------------------------------------------------------
  it('test_orchestrator_shows_subagent_checkboxes', () => {
    const steps: StepConfig[] = [{ agent_id: 'orchestrator' }]

    render(
      <StepConfigurator
        steps={steps}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )

    // Expand the panel by clicking its header button
    const toggleBtn = screen.getByText('Step 1 options').closest('button')!
    fireEvent.click(toggleBtn)

    // The sub-agents section label should appear
    expect(screen.getByText(/sub-agents/i)).toBeInTheDocument()
    // The non-orchestrator agents should appear as selectable buttons
    expect(screen.getByText('Data Analysis')).toBeInTheDocument()
    expect(screen.getByText('Visualization & Reporting')).toBeInTheDocument()
    // The orchestrator itself must NOT appear as its own sub-agent option
    expect(screen.queryByText('Orchestrator (Full Team)')).not.toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_non_orchestrator_hides_subagent_section
  // -----------------------------------------------------------------------
  it('test_non_orchestrator_hides_subagent_section', () => {
    const steps: StepConfig[] = [{ agent_id: 'data_analysis' }]

    render(
      <StepConfigurator
        steps={steps}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )

    // Expand the panel
    const toggleBtn = screen.getByText('Step 1 options').closest('button')!
    fireEvent.click(toggleBtn)

    // Sub-agents section should NOT appear for a non-orchestrator
    expect(screen.queryByText(/sub-agents/i)).not.toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_extra_instructions_textarea_present
  // -----------------------------------------------------------------------
  it('test_extra_instructions_textarea_present', () => {
    const steps: StepConfig[] = [{ agent_id: 'data_analysis' }]

    render(
      <StepConfigurator
        steps={steps}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )

    // Expand the panel
    const toggleBtn = screen.getByText('Step 1 options').closest('button')!
    fireEvent.click(toggleBtn)

    // The textarea for extra instructions should always be present
    const textarea = screen.getByRole('textbox')
    expect(textarea).toBeInTheDocument()
  })

  it('test_extra_instructions_textarea_present_for_orchestrator', () => {
    const steps: StepConfig[] = [{ agent_id: 'orchestrator' }]

    render(
      <StepConfigurator
        steps={steps}
        onChange={vi.fn()}
        availableAgents={availableAgents}
      />
    )

    const toggleBtn = screen.getByText('Step 1 options').closest('button')!
    fireEvent.click(toggleBtn)

    const textarea = screen.getByRole('textbox')
    expect(textarea).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test onChange is called when a sub-agent button is clicked
  // -----------------------------------------------------------------------
  it('test_onChange_called_on_sub_agent_toggle', () => {
    const onChange = vi.fn()
    const steps: StepConfig[] = [{ agent_id: 'orchestrator', sub_agents: [] }]

    render(
      <StepConfigurator
        steps={steps}
        onChange={onChange}
        availableAgents={availableAgents}
      />
    )

    // Expand the panel
    const toggleBtn = screen.getByText('Step 1 options').closest('button')!
    fireEvent.click(toggleBtn)

    // Click a sub-agent button
    const dataAnalysisBtn = screen.getByText('Data Analysis')
    fireEvent.click(dataAnalysisBtn)

    expect(onChange).toHaveBeenCalledTimes(1)
    const updatedSteps = onChange.mock.calls[0]![0] as StepConfig[]
    expect(updatedSteps[0]?.sub_agents).toContain('data_analysis')
  })
})
