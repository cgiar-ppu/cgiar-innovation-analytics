/**
 * Shared form fields for workflow name, description, and initial prompt.
 * Used by both CreateModal and ViewDialog.
 */

interface DetailsFormProps {
  name: string;
  onNameChange: (value: string) => void;
  description: string;
  onDescriptionChange: (value: string) => void;
  initialPrompt: string;
  onInitialPromptChange: (value: string) => void;
}

export default function DetailsForm({
  name,
  onNameChange,
  description,
  onDescriptionChange,
  initialPrompt,
  onInitialPromptChange,
}: DetailsFormProps) {
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest">
        Workflow Details
      </h3>

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2 sm:col-span-1">
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
            Name <span className="text-[var(--danger)]">*</span>
          </label>
          <input
            value={name}
            onChange={e => onNameChange(e.target.value)}
            placeholder="My Pipeline"
            className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors placeholder:text-[var(--text-muted)]"
          />
        </div>

        <div className="col-span-2 sm:col-span-1">
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
            Description
          </label>
          <input
            value={description}
            onChange={e => onDescriptionChange(e.target.value)}
            placeholder="What this pipeline does..."
            className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors placeholder:text-[var(--text-muted)]"
          />
        </div>

        <div className="col-span-2">
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
            Initial Prompt
          </label>
          <textarea
            value={initialPrompt}
            onChange={e => onInitialPromptChange(e.target.value)}
            placeholder="The default prompt to start the pipeline..."
            rows={3}
            className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors resize-none placeholder:text-[var(--text-muted)]"
          />
        </div>
      </div>
    </section>
  );
}
