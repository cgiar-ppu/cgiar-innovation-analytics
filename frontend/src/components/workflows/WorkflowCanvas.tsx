import { useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  ReactFlowProvider,
  type Node,
  type Edge,
  type NodeTypes,
  Position,
  MarkerType,
} from 'reactflow';
// Both style sheets are required: base.css provides layout primitives,
// style.css layers the default theme on top. Some glassmorphic host layouts
// only pick up one of the two, so we import both to be safe.
import 'reactflow/dist/base.css';
import 'reactflow/dist/style.css';
import GlassNode from './GlassNode';
import type { Workflow } from '../../lib/types-extended';

// Defined outside the component to avoid React Flow warning #002
const NODE_TYPES: NodeTypes = { glass: GlassNode };

interface WorkflowCanvasProps {
  workflow: Workflow;
}

// Inner component that owns the ReactFlow instance. Kept separate so the
// ReactFlowProvider wrapper (below) is always in the tree before ReactFlow
// mounts — this is required when multiple WorkflowCanvas instances render on
// the same page simultaneously.
/** Convert a snake_case agent key to a Title Case display label. */
function toLabel(key: string): string {
  return key
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function WorkflowCanvasInner({ workflow }: WorkflowCanvasProps) {
  const nodes: Node[] = useMemo(() => {
    // When the API returns empty nodes, synthesize them from agent_sequence so
    // the canvas always renders the pipeline rather than showing a blank frame.
    if (workflow.nodes.length > 0) {
      return workflow.nodes.map((n, i) => ({
        id: n.id,
        type: 'glass',
        position: n.position || { x: i * 280 + 50, y: 100 },
        data: {
          label: n.label,
          status: n.status,
          duration: n.duration,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      }));
    }

    return workflow.agent_sequence.map((agentKey, i) => ({
      id: `node-${i}`,
      type: 'glass',
      position: { x: i * 250 + 50, y: 100 },
      data: {
        label: toLabel(agentKey),
        status: workflow.status === 'completed' || workflow.status === 'failed'
          ? workflow.status
          : workflow.status === 'running'
          ? 'pending'
          : 'pending',
        duration: undefined,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));
  }, [workflow.nodes, workflow.agent_sequence, workflow.status]);

  const edges: Edge[] = useMemo(() => {
    // Mirror the node fallback: synthesize sequential edges from agent_sequence
    // when the API returns an empty edges array.
    if (workflow.edges.length > 0) {
      return workflow.edges.map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'smoothstep',
        animated: workflow.status === 'running',
        style: { stroke: 'var(--accent)', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--accent)' },
      }));
    }

    return workflow.agent_sequence.slice(0, -1).map((_, i) => ({
      id: `edge-${i}`,
      source: `node-${i}`,
      target: `node-${i + 1}`,
      type: 'smoothstep',
      animated: workflow.status === 'running',
      style: { stroke: 'var(--accent)', strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--accent)' },
    }));
  }, [workflow.edges, workflow.agent_sequence, workflow.status]);

  return (
    // w-full + h-full guarantee the ReactFlow root fills its parent. Without
    // an explicit width the flex/grid glassmorphic ancestors can collapse the
    // container to 0 px, producing a blank canvas.
    <div className="w-full h-full">
      <ReactFlow
        // key forces a full re-mount when the workflow changes, preventing
        // stale layout state from a previous workflow leaking through.
        key={workflow.id}
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        minZoom={0.5}
        maxZoom={1.5}
        // Read-only preview — users should not drag nodes or draw connections.
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border)" gap={20} size={1} />
        <Controls
          showInteractive={false}
          style={{
            background: 'var(--surface-2)',
            borderColor: 'var(--border)',
            borderRadius: '8px',
          }}
        />
      </ReactFlow>
    </div>
  );
}

export default function WorkflowCanvas({ workflow }: WorkflowCanvasProps) {
  return (
    // Outer container keeps the fixed height and visual chrome. w-full
    // combined with block display prevents glassmorphic parent flex containers
    // from collapsing the width to 0.
    <div className="w-full h-full rounded-lg overflow-hidden border border-[var(--border)] bg-[var(--surface-1)]">
      {/*
        ReactFlowProvider gives each canvas its own isolated store. Without it,
        multiple ReactFlow instances on the same page share internal state and
        can interfere with each other's fit-view calculations and drag state.
      */}
      <ReactFlowProvider>
        <WorkflowCanvasInner workflow={workflow} />
      </ReactFlowProvider>
    </div>
  );
}
