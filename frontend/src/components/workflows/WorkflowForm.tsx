/**
 * Re-export barrel — the real components live in ./WorkflowForm/ subdirectory.
 *
 * This file exists solely so that imports like
 *   import { CreateModal } from '../components/workflows/WorkflowForm'
 * resolve correctly regardless of bundler resolution order
 * (file WorkflowForm.tsx vs directory WorkflowForm/index.ts).
 */
export { CreateModal, WorkflowViewDialog } from './WorkflowForm/index';
export type { CreateModalProps } from './WorkflowForm/index';
export type { WorkflowViewDialogProps } from './WorkflowForm/index';
