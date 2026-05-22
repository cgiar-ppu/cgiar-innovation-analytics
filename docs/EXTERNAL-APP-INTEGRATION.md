# External App Integration Guide

> **Version:** 1.0 | **Last Updated:** 2026-04-06
> **Audience:** AI assistants and developers building frontends that connect to the Synapsis backend.
> This document is self-contained. You do not need access to the Synapsis source code.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Quick Start](#2-quick-start)
3. [API Reference](#3-api-reference)
4. [WebSocket Protocol](#4-websocket-protocol)
5. [File Handling](#5-file-handling)
6. [Building a React Mini-App](#6-building-a-react-mini-app)
7. [Deployment Options](#7-deployment-options)
8. [Configuration](#8-configuration)
9. [Common Patterns](#9-common-patterns)
10. [Troubleshooting](#10-troubleshooting)
11. [API Type Definitions](#11-api-type-definitions)

---

## 1. Overview

### What This Enables

Synapsis Analytics Agent is a FastAPI backend running on a Mac Mini, exposed to the internet via a reverse proxy at `https://synaptic.synapsis-analytics.com`. The reverse proxy terminates TLS, so the backend itself runs plain HTTP on port 7777 internally. External applications (React apps, dashboards, kiosks, CLI tools) hosted anywhere on the internet can:

- Send queries to specialized AI agents and receive structured responses
- Stream responses in real time over WebSocket
- Upload files for agents to process
- Download agent-generated results
- Cancel in-progress agent work

### Architecture

```
+------------------------------------------------------------------+
|                          Internet                                 |
|                                                                   |
|  +---------------------+                                         |
|  |  Mini-App (Vercel,  |  HTTPS/WSS                              |
|  |  Netlify, anywhere) | ------+                                 |
|  +---------------------+       |                                 |
|                                v                                 |
|  +---------------------+   +-------------------------------+     |
|  |  Another App        |   | Reverse Proxy (TLS)           |     |
|  |  (phone, kiosk,     |-->| synaptic.synapsis-analytics   |     |
|  |   local dev, CLI)   |   |          .com                 |     |
|  +---------------------+   +-------------------------------+     |
|                                |  HTTP (internal)                |
|                                v                                 |
|                          +---------------------------+            |
|                          |   Synapsis Backend        |            |
|                          |   FastAPI on Mac Mini     |            |
|                          |   Port 7777 (internal)    |            |
|                          |                           |            |
|                          |   /api/agents/*/query     |            |
|                          |   /ws/agent/*             |            |
|                          |   /api/upload             |            |
|                          |   /api/files/*            |            |
|                          |   /api/agents             |            |
|                          |                           |            |
|                          |   +---------+---------+   |            |
|                          |   | Agent 1 | Agent 2 |   |            |
|                          |   | Agent 3 | Agent N |   |            |
|                          |   +---------+---------+   |            |
|                          +---------------------------+            |
+------------------------------------------------------------------+
```

### Key Architectural Points

- **Production URL:** `https://synaptic.synapsis-analytics.com` -- the public endpoint for all API and WebSocket traffic.
- **Server:** FastAPI running on a Mac Mini, exposed via a reverse proxy that terminates TLS.
- **Internal port:** 7777 (not directly accessible from the internet).
- **Authentication:** None. The reverse proxy handles TLS but does not add authentication.
- **CORS:** Open by default (`*`), configurable via environment variable. This means mini-apps can be hosted anywhere (Vercel, Netlify, local dev, etc.).
- **Two communication modes:**
  - **REST** (`POST /api/agents/{agent_id}/query`) -- stateless, single-turn, returns complete response.
  - **WebSocket** (`WSS /ws/agent/{agent_id}`) -- stateful, multi-turn, streams partial responses in real time.
- **Agents** are specialized AI personas with different tools and system prompts. Each has a unique `agent_id`.

---

## 2. Quick Start

### Minimal REST Example (10 lines of JavaScript)

```javascript
const SYNAPSIS_URL = "https://synaptic.synapsis-analytics.com";

async function askAgent(agentId, message) {
  const res = await fetch(`${SYNAPSIS_URL}/api/agents/${agentId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();
  return data.response;
}

// Usage:
const answer = await askAgent("data_analysis", "What statistical test should I use for comparing two groups?");
console.log(answer);
```

### Minimal WebSocket Example

```javascript
const ws = new WebSocket("wss://synaptic.synapsis-analytics.com/ws/agent/data_analysis");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "text") process.stdout.write(msg.content);
  if (msg.type === "result") console.log("\n[Done]", msg);
};

ws.onopen = () => {
  ws.send(JSON.stringify({ message: "Explain p-values in simple terms" }));
};
```

### Verify the Backend is Running

```bash
curl https://synaptic.synapsis-analytics.com/api/agents
```

If successful, you will receive a JSON object with an `agents` array.

---

## 3. API Reference

### 3.1 List Available Agents

Returns all agents the backend has registered (builtin + custom).

```
GET /api/agents
```

**Response:**

```json
{
  "agents": [
    {
      "id": "data_analysis",
      "name": "Data Analysis",
      "description": "Statistical analysis and data wrangling specialist...",
      "type": "builtin",
      "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
      "model": "opus"
    },
    {
      "id": "computer_use",
      "name": "Computer Use",
      "description": "GUI interaction, browsers, screenshots, clicking",
      "type": "builtin",
      "tools": ["Bash", "mcp__synapsis__computer"],
      "model": "opus"
    }
  ]
}
```

### 3.2 Get Agent Details

Returns full details for a single agent, including its system prompt.

```
GET /api/agents/{agent_id}
```

**Path Parameters:**

| Parameter  | Type   | Description                        |
|-----------|--------|------------------------------------|
| `agent_id` | string | The unique identifier of the agent |

**Response:** A single agent object (same shape as items in the agents array, but may include additional fields like `system_prompt`).

**Example:**

```
GET /api/agents/data_analysis
```

```json
{
  "id": "data_analysis",
  "name": "Data Analysis",
  "description": "Statistical analysis and data wrangling specialist...",
  "type": "builtin",
  "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
  "model": "opus",
  "system_prompt": "You are the Data Analysis specialist..."
}
```

### 3.3 Direct Agent Query (REST -- Stateless, Single-Turn)

Send a message to a specific agent and receive the complete response. This is the simplest integration path. The request blocks until the agent finishes all its work (which may take seconds to minutes depending on complexity).

```
POST /api/agents/{agent_id}/query
Content-Type: application/json
```

**Path Parameters:**

| Parameter  | Type   | Description                        |
|-----------|--------|------------------------------------|
| `agent_id` | string | The unique identifier of the agent |

**Request Body:**

| Field                | Type   | Required | Description                                            |
|---------------------|--------|----------|--------------------------------------------------------|
| `message`           | string | Yes      | The user's message or instruction                      |
| `extra_instructions`| string | No       | Additional context appended to the system prompt for this query only |

**Example Request:**

```json
{
  "message": "Analyze the file at /Users/smithai/workspace/uploads/sales.csv and give me a summary",
  "extra_instructions": "Focus on monthly trends and outliers. Output charts as HTML files."
}
```

**Response:**

```json
{
  "response": "## Sales Data Analysis\n\nI analyzed the file and found the following...",
  "tool_uses": [
    {
      "tool": "Bash",
      "input": {
        "command": "python3 /Users/smithai/workspace/scripts/analyze_sales.py",
        "description": "Run sales analysis script"
      }
    },
    {
      "tool": "Write",
      "input": {
        "file_path": "/Users/smithai/workspace/outputs/sales_chart.html",
        "content": "..."
      }
    }
  ],
  "result": {
    "estimated_cost": 0.05,
    "turns": 3,
    "duration_ms": 12500
  },
  "agent_id": "data_analysis",
  "agent_name": "Data Analysis"
}
```

**Response Fields:**

| Field         | Type   | Description                                                    |
|--------------|--------|----------------------------------------------------------------|
| `response`   | string | The agent's full text response (Markdown formatted)            |
| `tool_uses`  | array  | List of tools the agent invoked during processing              |
| `result`     | object | Metadata: cost estimate, number of agentic turns, duration     |
| `agent_id`   | string | ID of the agent that handled the request                       |
| `agent_name` | string | Human-readable name of the agent                               |

### 3.4 File Upload

Upload a file to the server so agents can access it.

```
POST /api/upload
Content-Type: multipart/form-data
```

**Form Fields:**

| Field  | Type | Required | Description     |
|--------|------|----------|-----------------|
| `file` | file | Yes      | The file to upload |

**Example (JavaScript):**

```javascript
const formData = new FormData();
formData.append("file", fileInput.files[0]);

const res = await fetch(`${SYNAPSIS_URL}/api/upload`, {
  method: "POST",
  body: formData,
});
const data = await res.json();
// data.path = "/Users/smithai/workspace/uploads/yourfile.xlsx"
```

**Example (curl):**

```bash
curl -X POST https://synaptic.synapsis-analytics.com/api/upload \
  -F "file=@/path/to/local/report.xlsx"
```

**Response:**

```json
{
  "path": "/Users/smithai/workspace/uploads/report.xlsx",
  "size": 245890
}
```

### 3.5 File Download

Download a file from the workspace by its relative path (relative to `~/workspace/`).

```
GET /api/files/{relative_path}
```

**Path Parameters:**

| Parameter       | Type   | Description                                              |
|----------------|--------|----------------------------------------------------------|
| `relative_path` | string | Path relative to the workspace root (`~/workspace/`)     |

**Examples:**

```
GET /api/files/outputs/analysis.xlsx
GET /api/files/outputs/chart.html
GET /api/files/uploads/original.csv
```

**Response:** The raw file content with appropriate `Content-Type` and `Content-Disposition` headers for download.

**Example (JavaScript):**

```javascript
// Download and save a file
const res = await fetch(`${SYNAPSIS_URL}/api/files/outputs/analysis.xlsx`);
const blob = await res.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
a.download = "analysis.xlsx";
a.click();
URL.revokeObjectURL(url);
```

### 3.6 Full Orchestrator (Stateless REST)

Instead of targeting a specific agent, you can send a query to the orchestrator, which will automatically route it to the appropriate agent(s).

```
POST /api/query
Content-Type: application/json
```

**Request Body:**

```json
{
  "message": "Create a bar chart from my sales data"
}
```

**Response:** Same shape as the direct agent query response.

### 3.7 Full Orchestrator (WebSocket Streaming)

Session-based streaming through the orchestrator. Same protocol as the direct agent WebSocket (see Section 4) but routes through the orchestrator.

```
WS /ws/chat
```

---

## 4. WebSocket Protocol

The WebSocket endpoint provides real-time streaming of agent responses, multi-turn conversations, and cancellation support.

### 4.1 Connection

```
WS /ws/agent/{agent_id}
```

**Production:** `wss://synaptic.synapsis-analytics.com/ws/agent/data_analysis`

**Local development:** `ws://localhost:7777/ws/agent/data_analysis`

### 4.2 Connection Lifecycle

```
Client                                Server
  |                                     |
  |  --- WebSocket CONNECT ---------->  |
  |  <-- agent_info ------------------  |  (immediate, identifies the agent)
  |                                     |
  |  --- {message: "..."} ----------->  |  (client sends a query)
  |  <-- {type: "thinking", ...} -----  |  (zero or more thinking blocks)
  |  <-- {type: "text", ...} ---------  |  (streaming text chunks)
  |  <-- {type: "text", ...} ---------  |  (more chunks)
  |  <-- {type: "tool_use", ...} -----  |  (agent invokes a tool)
  |  <-- {type: "tool_result", ...} --  |  (tool execution result)
  |  <-- {type: "text", ...} ---------  |  (agent continues after tool)
  |  <-- {type: "result", ...} -------  |  (final result with metadata)
  |                                     |
  |  --- {message: "..."} ----------->  |  (another turn in same session)
  |  <-- {type: "text", ...} ---------  |
  |  <-- {type: "result", ...} -------  |
  |                                     |
  |  --- {type: "cancel"} ----------->  |  (cancel in-progress work)
  |  <-- {type: "cancelled"} ---------  |
  |                                     |
  |  --- WebSocket CLOSE ------------>  |
  |                                     |
```

### 4.3 Client-to-Server Messages

#### Send a Query

```json
{
  "message": "Your question or instruction here"
}
```

#### Send a Query with Extra Instructions

```json
{
  "message": "Analyze the uploaded file",
  "extra_instructions": "Use pandas. Save results as CSV to /Users/smithai/workspace/outputs/"
}
```

#### Cancel In-Progress Work

```json
{
  "type": "cancel"
}
```

### 4.4 Server-to-Client Messages

All messages are JSON objects with a `type` field.

#### `agent_info` -- Sent immediately after connection

```json
{
  "type": "agent_info",
  "agent_id": "data_analysis",
  "agent_name": "Data Analysis"
}
```

#### `text` -- Streaming text content

Arrives in small chunks as the agent generates text. Concatenate all `text` chunks to build the full response.

```json
{
  "type": "text",
  "content": "Here is the partial response tex"
}
```

#### `thinking` -- Agent reasoning (extended thinking blocks)

Shows the agent's internal reasoning process. These can be displayed in a collapsible UI element or hidden.

```json
{
  "type": "thinking",
  "content": "I need to first read the CSV file to understand its structure..."
}
```

#### `tool_generating` -- Early indicator that a tool is being prepared

Sent as soon as the agent starts generating a tool call, before the full input is ready. Use this to show "Preparing Bash..." in the UI.

```json
{
  "type": "tool_generating",
  "tool": "Bash",
  "tool_use_id": "toolu_abc123"
}
```

#### `tool_input_delta` -- Streaming tool input construction

Partial JSON chunks as the agent builds the tool input. Optional to handle — only useful for showing real-time tool input construction.

```json
{
  "type": "tool_input_delta",
  "content": "{\"command\": \"python3 -c \\\"import"
}
```

#### `tool_use` -- Agent is invoking a tool

The agent has decided to use a tool. This is the complete tool call with all parameters. Arrives after `tool_generating` and all `tool_input_delta` messages for this tool.

```json
{
  "type": "tool_use",
  "tool": "Bash",
  "input": {
    "command": "python3 -c \"import pandas as pd; df = pd.read_csv('/Users/smithai/workspace/uploads/data.csv'); print(df.describe())\"",
    "description": "Load CSV and print summary statistics"
  },
  "tool_use_id": "toolu_abc123"
}
```

#### `tool_result` -- Result of a tool execution

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_abc123",
  "content": "       col_a    col_b\ncount  100.0    100.0\nmean    50.3     75.1\n...",
  "is_error": false
}
```

#### `result` -- Final result metadata (marks end of a turn)

This is always the last message for a given query. It signals that the agent has finished.

```json
{
  "type": "result",
  "estimated_cost": 0.05,
  "turns": 3,
  "duration_ms": 12500
}
```

#### `cancelled` -- Confirms cancellation

```json
{
  "type": "cancelled"
}
```

#### `system` -- Internal system event (optional)

SDK lifecycle events. Most frontends can safely ignore these.

```json
{
  "type": "system",
  "subtype": "init",
  "data": "{\"session_id\": \"abc123\"}"
}
```

#### `error` -- An error occurred

```json
{
  "type": "error",
  "message": "Agent not found: invalid_agent_id"
}
```

### 4.5 Message Type Summary

| Type               | Direction       | When                                          | Required to handle? |
|-------------------|-----------------|-----------------------------------------------|---------------------|
| `agent_info`       | Server→Client  | Once, immediately after connection             | **Yes** |
| `text`             | Server→Client  | Multiple times during response streaming       | **Yes** |
| `thinking`         | Server→Client  | Zero or more times during agent reasoning      | Optional (show/hide) |
| `tool_generating`  | Server→Client  | When agent starts preparing a tool call        | Optional (early indicator) |
| `tool_input_delta` | Server→Client  | As tool input JSON is being constructed        | Optional (real-time preview) |
| `tool_use`         | Server→Client  | When complete tool call is ready               | **Yes** |
| `tool_result`      | Server→Client  | After tool execution completes                 | **Yes** |
| `system`           | Server→Client  | SDK lifecycle events                           | Optional (debug) |
| `result`           | Server→Client  | Once, at the end of each query                 | **Yes** (marks turn end) |
| `cancelled`        | Server→Client  | Once, after a cancel request is processed      | **Yes** |
| `error`            | Server→Client  | When an error occurs                           | **Yes** |

### 4.6 Important Notes

- **Multi-turn:** The WebSocket stays open. You can send multiple queries sequentially. Each query gets its own stream of messages ending with a `result` message.
- **One query at a time:** Do not send a new query until the current one finishes (you receive a `result` or `cancelled` or `error` message).
- **Text reconstruction:** Concatenate all `text` message `content` fields in order to build the full response.
- **Markdown:** Agent responses are Markdown-formatted. Use a Markdown renderer for best display.

---

## 5. File Handling

### 5.1 Upload Flow

```
[User selects file] --> POST /api/upload --> Server saves to ~/workspace/uploads/
                                         --> Returns { path, size }
```

### 5.2 Referencing Uploaded Files in Messages

After uploading, include the returned `path` in your message to the agent using this exact format:

```
[Attached files]
  report.xlsx -> /Users/smithai/workspace/uploads/report.xlsx
[End attached files]

Please analyze this sales report and create a summary chart.
```

Multiple files:

```
[Attached files]
  sales_q1.csv -> /Users/smithai/workspace/uploads/sales_q1.csv
  sales_q2.csv -> /Users/smithai/workspace/uploads/sales_q2.csv
[End attached files]

Compare Q1 and Q2 sales data and highlight differences.
```

### 5.3 Downloading Agent Results

Agents typically save their outputs to `~/workspace/outputs/`. After the agent responds, you can:

1. Parse the agent's response text for file paths (they will usually mention what they saved and where).
2. Download via `GET /api/files/outputs/{filename}`.

**Common output locations:**

| Path Pattern             | Description                 |
|-------------------------|-----------------------------|
| `outputs/*.xlsx`        | Excel spreadsheets          |
| `outputs/*.csv`         | CSV data files              |
| `outputs/*.html`        | HTML reports and charts     |
| `outputs/*.png`         | Images and charts           |
| `scripts/*.py`          | Generated Python scripts    |
| `analysis/*`            | Analysis artifacts          |

### 5.4 Complete Upload-Process-Download Flow

```javascript
// 1. Upload a file
const formData = new FormData();
formData.append("file", file);
const uploadRes = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: formData });
const { path } = await uploadRes.json();

// 2. Ask an agent to process it
const queryRes = await fetch(`${BASE_URL}/api/agents/data_analysis/query`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    message: `[Attached files]\n  ${file.name} -> ${path}\n[End attached files]\n\nAnalyze this data and save a summary to /Users/smithai/workspace/outputs/summary.csv`,
  }),
});
const { response } = await queryRes.json();

// 3. Download the result
const downloadRes = await fetch(`${BASE_URL}/api/files/outputs/summary.csv`);
const blob = await downloadRes.blob();
```

### 5.5 Workspace Directory Structure

```
~/workspace/
  uploads/     <-- User-uploaded files land here (via POST /api/upload)
  outputs/     <-- Agent-generated results are saved here
  analysis/    <-- Analysis-specific outputs
  scripts/     <-- Generated or reusable scripts
```

---

## 6. Building a React Mini-App

This section walks through building a complete React + TypeScript mini-app that connects to the Synapsis backend.

### 6.1 Project Setup

```bash
npm create vite@latest my-synapsis-app -- --template react-ts
cd my-synapsis-app
npm install
```

No additional dependencies are required. The app uses only the browser-native `fetch` and `WebSocket` APIs.

Optional but recommended:

```bash
npm install react-markdown     # Render Markdown responses
```

### 6.2 Environment Configuration

Create a `.env` file at the project root:

```env
# Production (default -- connects to the public reverse proxy)
VITE_SYNAPSIS_URL=https://synaptic.synapsis-analytics.com

# Local development (uncomment to use instead)
# VITE_SYNAPSIS_URL=http://localhost:7777
```

Access it in code as `import.meta.env.VITE_SYNAPSIS_URL`.

### 6.3 API Client Utility

Create `src/lib/synapsis-api.ts`:

```typescript
// src/lib/synapsis-api.ts
//
// Complete API client for the Synapsis backend.
// All methods return typed responses. No external dependencies.

const BASE_URL =
  import.meta.env.VITE_SYNAPSIS_URL ?? "https://synaptic.synapsis-analytics.com";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Agent {
  id: string;
  name: string;
  description: string;
  type: "builtin" | "custom";
  tools: string[];
  model: string;
}

export interface AgentListResponse {
  agents: Agent[];
}

export interface ToolUse {
  tool: string;
  input: Record<string, unknown>;
}

export interface QueryResult {
  estimated_cost: number;
  turns: number;
  duration_ms: number;
}

export interface AgentQueryResponse {
  response: string;
  tool_uses: ToolUse[];
  result: QueryResult;
  agent_id: string;
  agent_name: string;
}

export interface UploadResponse {
  path: string;
  size: number;
}

export interface QueryRequest {
  message: string;
  extra_instructions?: string;
}

// ---------------------------------------------------------------------------
// API Functions
// ---------------------------------------------------------------------------

/** List all available agents. */
export async function listAgents(): Promise<AgentListResponse> {
  const res = await fetch(`${BASE_URL}/api/agents`);
  if (!res.ok) throw new Error(`Failed to list agents: ${res.status}`);
  return res.json();
}

/** Get details for a single agent. */
export async function getAgent(agentId: string): Promise<Agent> {
  const res = await fetch(`${BASE_URL}/api/agents/${agentId}`);
  if (!res.ok) throw new Error(`Failed to get agent: ${res.status}`);
  return res.json();
}

/** Send a single-turn query to an agent and wait for the full response. */
export async function queryAgent(
  agentId: string,
  request: QueryRequest
): Promise<AgentQueryResponse> {
  const res = await fetch(`${BASE_URL}/api/agents/${agentId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Agent query failed (${res.status}): ${text}`);
  }
  return res.json();
}

/** Send a query through the orchestrator (auto-routes to the best agent). */
export async function queryOrchestrator(
  request: QueryRequest
): Promise<AgentQueryResponse> {
  const res = await fetch(`${BASE_URL}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Orchestrator query failed (${res.status}): ${text}`);
  }
  return res.json();
}

/** Upload a file so agents can access it. */
export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${BASE_URL}/api/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

/** Get the download URL for a workspace file. */
export function getFileUrl(relativePath: string): string {
  // Strip leading slash or ~/workspace/ prefix if accidentally included
  const clean = relativePath
    .replace(/^\/Users\/smithai\/workspace\//, "")
    .replace(/^~\/workspace\//, "")
    .replace(/^\//, "");
  return `${BASE_URL}/api/files/${clean}`;
}

/** Download a file from the workspace as a Blob. */
export async function downloadFile(relativePath: string): Promise<Blob> {
  const res = await fetch(getFileUrl(relativePath));
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  return res.blob();
}

/** Trigger a browser file-save dialog for a workspace file. */
export async function saveFile(relativePath: string, filename?: string): Promise<void> {
  const blob = await downloadFile(relativePath);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename ?? relativePath.split("/").pop() ?? "download";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Build a message string that includes attached file references.
 *
 * @param message - The user's question or instruction
 * @param files - Array of { name, path } objects from previous uploads
 */
export function buildMessageWithFiles(
  message: string,
  files: { name: string; path: string }[]
): string {
  if (files.length === 0) return message;
  const fileList = files.map((f) => `  ${f.name} -> ${f.path}`).join("\n");
  return `[Attached files]\n${fileList}\n[End attached files]\n\n${message}`;
}

/** Return the base URL (useful for constructing WebSocket URLs). */
export function getBaseUrl(): string {
  return BASE_URL;
}

/**
 * Convert the HTTP base URL to a WebSocket URL.
 * https:// becomes wss://, http:// becomes ws://.
 */
export function getWsBaseUrl(): string {
  return BASE_URL.replace(/^http/, "ws");
}
```

### 6.4 WebSocket Hook

Create `src/hooks/useSynapsisAgent.ts`:

```typescript
// src/hooks/useSynapsisAgent.ts
//
// React hook for streaming WebSocket communication with a Synapsis agent.
// Provides: connect, send messages, receive streaming updates, cancel.

import { useCallback, useEffect, useRef, useState } from "react";
import { getWsBaseUrl } from "../lib/synapsis-api";

// ---------------------------------------------------------------------------
// Types for WebSocket messages
// ---------------------------------------------------------------------------

export interface WsAgentInfo {
  type: "agent_info";
  agent_id: string;
  agent_name: string;
}

export interface WsText {
  type: "text";
  content: string;
}

export interface WsThinking {
  type: "thinking";
  content: string;
}

export interface WsToolGenerating {
  type: "tool_generating";
  tool: string;
  tool_use_id: string;
}

export interface WsToolInputDelta {
  type: "tool_input_delta";
  content: string;
}

export interface WsToolUse {
  type: "tool_use";
  tool: string;
  input: Record<string, unknown>;
  tool_use_id: string;
}

export interface WsToolResult {
  type: "tool_result";
  tool_use_id: string;
  content: string;
  is_error: boolean;
}

export interface WsSystem {
  type: "system";
  subtype: string;
  data: string | null;
}

export interface WsResult {
  type: "result";
  estimated_cost: number;
  turns: number;
  duration_ms: number;
  session_id?: string;
}

export interface WsCancelled {
  type: "cancelled";
}

export interface WsError {
  type: "error";
  message: string;
}

export type WsServerMessage =
  | WsAgentInfo
  | WsText
  | WsThinking
  | WsToolGenerating
  | WsToolInputDelta
  | WsToolUse
  | WsToolResult
  | WsSystem
  | WsResult
  | WsCancelled
  | WsError;

export interface WsClientQuery {
  message: string;
  extra_instructions?: string;
}

export interface WsClientCancel {
  type: "cancel";
}

export type WsClientMessage = WsClientQuery | WsClientCancel;

// ---------------------------------------------------------------------------
// Hook state
// ---------------------------------------------------------------------------

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export interface ToolActivity {
  tool: string;
  input: Record<string, unknown>;
  tool_use_id: string;
  result?: string;
  is_error?: boolean;
}

export interface UseSynapsisAgentReturn {
  /** Current WebSocket connection status. */
  status: ConnectionStatus;
  /** The agent's display name (populated after connection). */
  agentName: string;
  /** Accumulated text response for the current query. */
  responseText: string;
  /** Whether the agent is currently processing a query. */
  isProcessing: boolean;
  /** List of tool invocations in the current query. */
  tools: ToolActivity[];
  /** Thinking blocks for the current query. */
  thinking: string[];
  /** Result metadata from the last completed query. */
  lastResult: WsResult | null;
  /** Error message, if any. */
  error: string | null;
  /** Send a message to the agent. Resets response state. */
  sendMessage: (message: string, extraInstructions?: string) => void;
  /** Cancel the current in-progress query. */
  cancel: () => void;
  /** Manually disconnect the WebSocket. */
  disconnect: () => void;
  /** Manually reconnect to the same agent. */
  reconnect: () => void;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function useSynapsisAgent(agentId: string): UseSynapsisAgentReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [agentName, setAgentName] = useState("");
  const [responseText, setResponseText] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [tools, setTools] = useState<ToolActivity[]>([]);
  const [thinking, setThinking] = useState<string[]>([]);
  const [lastResult, setLastResult] = useState<WsResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(() => {
    // Close any existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    setStatus("connecting");
    setError(null);

    const wsUrl = `${getWsBaseUrl()}/ws/agent/${agentId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
    };

    ws.onclose = () => {
      setStatus("disconnected");
      setIsProcessing(false);
    };

    ws.onerror = () => {
      setStatus("error");
      setError("WebSocket connection failed");
      setIsProcessing(false);
    };

    ws.onmessage = (event: MessageEvent) => {
      let msg: WsServerMessage;
      try {
        msg = JSON.parse(event.data);
      } catch {
        console.error("Failed to parse WebSocket message:", event.data);
        return;
      }

      switch (msg.type) {
        case "agent_info":
          setAgentName(msg.agent_name);
          break;

        case "text":
          setResponseText((prev) => prev + msg.content);
          break;

        case "thinking":
          setThinking((prev) => [...prev, msg.content]);
          break;

        case "tool_use":
          setTools((prev) => [
            ...prev,
            {
              tool: msg.tool,
              input: msg.input,
              tool_use_id: msg.tool_use_id,
            },
          ]);
          break;

        case "tool_result":
          setTools((prev) =>
            prev.map((t) =>
              t.tool_use_id === msg.tool_use_id
                ? { ...t, result: msg.content, is_error: msg.is_error }
                : t
            )
          );
          break;

        case "result":
          setLastResult(msg);
          setIsProcessing(false);
          break;

        case "cancelled":
          setIsProcessing(false);
          break;

        case "error":
          setError(msg.message);
          setIsProcessing(false);
          break;
      }
    };
  }, [agentId]);

  // Auto-connect on mount and when agentId changes
  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback(
    (message: string, extraInstructions?: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setError("WebSocket is not connected");
        return;
      }

      // Reset state for new query
      setResponseText("");
      setTools([]);
      setThinking([]);
      setLastResult(null);
      setError(null);
      setIsProcessing(true);

      const payload: WsClientQuery = { message };
      if (extraInstructions) {
        payload.extra_instructions = extraInstructions;
      }
      wsRef.current.send(JSON.stringify(payload));
    },
    []
  );

  const cancel = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "cancel" }));
    }
  }, []);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  return {
    status,
    agentName,
    responseText,
    isProcessing,
    tools,
    thinking,
    lastResult,
    error,
    sendMessage,
    cancel,
    disconnect,
    reconnect: connect,
  };
}
```

### 6.5 File Upload Component

Create `src/components/FileUpload.tsx`:

```tsx
// src/components/FileUpload.tsx

import { useCallback, useState } from "react";
import { uploadFile, type UploadResponse } from "../lib/synapsis-api";

interface FileUploadProps {
  onUploaded: (result: UploadResponse & { name: string }) => void;
  accept?: string; // e.g., ".xlsx,.csv,.json"
}

export function FileUpload({ onUploaded, accept }: FileUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setUploading(true);
      setError(null);

      try {
        const result = await uploadFile(file);
        onUploaded({ ...result, name: file.name });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
        // Reset input so the same file can be re-uploaded
        e.target.value = "";
      }
    },
    [onUploaded]
  );

  return (
    <div>
      <label
        style={{
          display: "inline-block",
          padding: "8px 16px",
          background: uploading ? "#ccc" : "#0066cc",
          color: "#fff",
          borderRadius: "6px",
          cursor: uploading ? "wait" : "pointer",
        }}
      >
        {uploading ? "Uploading..." : "Upload File"}
        <input
          type="file"
          accept={accept}
          onChange={handleChange}
          disabled={uploading}
          style={{ display: "none" }}
        />
      </label>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
```

### 6.6 Chat Interface Component

Create `src/components/AgentChat.tsx`:

```tsx
// src/components/AgentChat.tsx
//
// A complete chat interface that streams responses from a Synapsis agent.

import { FormEvent, useRef, useState } from "react";
import { useSynapsisAgent } from "../hooks/useSynapsisAgent";
import { FileUpload } from "./FileUpload";
import { buildMessageWithFiles, type UploadResponse } from "../lib/synapsis-api";

interface AgentChatProps {
  agentId: string;
  /** Extra instructions to send with every query. */
  extraInstructions?: string;
  /** Accepted file types for upload, e.g. ".xlsx,.csv" */
  acceptFiles?: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export function AgentChat({ agentId, extraInstructions, acceptFiles }: AgentChatProps) {
  const {
    status,
    agentName,
    responseText,
    isProcessing,
    tools,
    error,
    sendMessage,
    cancel,
    reconnect,
  } = useSynapsisAgent(agentId);

  const [input, setInput] = useState("");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<{ name: string; path: string }[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isProcessing) return;

    const fullMessage = buildMessageWithFiles(input.trim(), uploadedFiles);

    // Add user message to history
    setHistory((prev) => [...prev, { role: "user", content: input.trim() }]);
    setInput("");
    setUploadedFiles([]);

    sendMessage(fullMessage, extraInstructions);
  };

  const handleUploaded = (result: UploadResponse & { name: string }) => {
    setUploadedFiles((prev) => [...prev, { name: result.name, path: result.path }]);
  };

  // When processing finishes and we have response text, add to history
  // (This is simplified -- in production you'd use useEffect to detect the transition)
  const allMessages = [
    ...history,
    ...(responseText ? [{ role: "assistant" as const, content: responseText }] : []),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", fontFamily: "system-ui" }}>
      {/* Header */}
      <div style={{ padding: "12px 16px", borderBottom: "1px solid #e0e0e0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <strong>{agentName || agentId}</strong>
          <span style={{ marginLeft: 8, fontSize: 12, color: status === "connected" ? "green" : "red" }}>
            {status}
          </span>
        </div>
        {status !== "connected" && (
          <button onClick={reconnect} style={{ fontSize: 12 }}>
            Reconnect
          </button>
        )}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
        {allMessages.map((msg, i) => (
          <div
            key={i}
            style={{
              marginBottom: 12,
              padding: "10px 14px",
              borderRadius: 8,
              background: msg.role === "user" ? "#e3f2fd" : "#f5f5f5",
              maxWidth: "80%",
              marginLeft: msg.role === "user" ? "auto" : 0,
              whiteSpace: "pre-wrap",
            }}
          >
            {msg.content}
          </div>
        ))}

        {/* Tool activity indicators */}
        {isProcessing && tools.length > 0 && (
          <div style={{ fontSize: 12, color: "#666", margin: "8px 0" }}>
            {tools.map((t, i) => (
              <div key={i}>
                Tool: {t.tool} {t.result !== undefined ? "(done)" : "(running...)"}
              </div>
            ))}
          </div>
        )}

        {isProcessing && !responseText && (
          <div style={{ color: "#999", fontStyle: "italic" }}>Thinking...</div>
        )}

        {error && <div style={{ color: "red", padding: 8 }}>{error}</div>}

        <div ref={bottomRef} />
      </div>

      {/* Uploaded files preview */}
      {uploadedFiles.length > 0 && (
        <div style={{ padding: "4px 16px", fontSize: 12, color: "#666" }}>
          Attached: {uploadedFiles.map((f) => f.name).join(", ")}
        </div>
      )}

      {/* Input area */}
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, padding: "12px 16px", borderTop: "1px solid #e0e0e0" }}>
        {acceptFiles && <FileUpload onUploaded={handleUploaded} accept={acceptFiles} />}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={status !== "connected"}
          style={{ flex: 1, padding: "8px 12px", borderRadius: 6, border: "1px solid #ccc" }}
        />
        {isProcessing ? (
          <button type="button" onClick={cancel} style={{ padding: "8px 16px", background: "#cc0000", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            Cancel
          </button>
        ) : (
          <button type="submit" disabled={status !== "connected" || !input.trim()} style={{ padding: "8px 16px", background: "#0066cc", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            Send
          </button>
        )}
      </form>
    </div>
  );
}
```

### 6.7 Complete Example: "Excel Expert" Mini-App

This is a complete `App.tsx` for a mini-app that lets users upload Excel files and ask questions about them.

```tsx
// src/App.tsx
import { AgentChat } from "./components/AgentChat";

export default function App() {
  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <AgentChat
        agentId="data_analysis"
        extraInstructions="The user is working with Excel files. When analyzing data, use pandas and openpyxl. Save any output files to /Users/smithai/workspace/outputs/. Provide download links as relative paths like outputs/filename.xlsx."
        acceptFiles=".xlsx,.xls,.csv"
      />
    </div>
  );
}
```

That is all you need. Run `npm run dev` and open the browser.

---

## 7. Deployment Options

The Synapsis backend is publicly available at `https://synaptic.synapsis-analytics.com`. Because CORS is enabled (`*` by default), mini-apps can be hosted **anywhere** and connect to the production API. There is no need to co-locate mini-apps on the Mac Mini or set up subdomains.

### Option A: Host Anywhere + Point to Production API (Recommended)

Deploy your mini-app to any static hosting provider (Vercel, Netlify, Cloudflare Pages, GitHub Pages, your own server) and configure it to use the production API.

```env
VITE_SYNAPSIS_URL=https://synaptic.synapsis-analytics.com
```

Your app makes HTTPS requests and WSS connections to `synaptic.synapsis-analytics.com` regardless of where it is hosted. CORS is handled server-side.

**Pros:** Simplest production setup, deploy mini-apps independently, no server access needed.
**Cons:** None for most use cases.

### Option B: Static Files Served by Synapsis

Build your React app and place the output in a folder the Synapsis server can serve.

```bash
cd my-synapsis-app
npm run build
cp -r dist/ /path/to/synapsis/static/my-app/
```

The app will be available at `https://synaptic.synapsis-analytics.com/static/my-app/index.html` (exact path depends on Synapsis static file configuration).

**Pros:** Single origin, no CORS issues.
**Cons:** Requires access to the Mac Mini file system.

### Option C: Local Dev Server with Proxy (For Development)

Run Vite's dev server locally and proxy API calls to the production backend (or a local instance).

Add to `vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "https://synaptic.synapsis-analytics.com",
        changeOrigin: true,
        secure: true,
      },
      "/ws": {
        target: "wss://synaptic.synapsis-analytics.com",
        ws: true,
        secure: true,
      },
    },
  },
});
```

Then in your code, use relative URLs (`/api/agents`, `/ws/agent/...`) instead of absolute ones. Set `VITE_SYNAPSIS_URL` to empty string or omit it.

> **Local development alternative:** If you are running the Synapsis backend locally, replace the proxy targets with `http://localhost:7777` and `ws://localhost:7777` respectively.

**Pros:** Hot-reload during development, no CORS concerns.
**Cons:** Only for development.

---

## 8. Configuration

### Server URL Configuration

| Environment | Base URL | WebSocket URL |
|-------------|----------|---------------|
| **Production** | `https://synaptic.synapsis-analytics.com` | `wss://synaptic.synapsis-analytics.com` |
| **Local development** | `http://localhost:7777` | `ws://localhost:7777` |

The mini-app should read the base URL from an environment variable so you can switch between production and local development without code changes:

```env
# .env (production -- this is the default if the variable is not set)
VITE_SYNAPSIS_URL=https://synaptic.synapsis-analytics.com

# .env.local (local development override)
VITE_SYNAPSIS_URL=http://localhost:7777
```

In your API client, derive the WebSocket URL from the base URL:

```typescript
const baseUrl =
  import.meta.env.VITE_SYNAPSIS_URL ?? "https://synaptic.synapsis-analytics.com";

// https:// -> wss://, http:// -> ws://
const wsBase = baseUrl.replace(/^http/, "ws");
```

This ensures that `https` correctly maps to `wss` and `http` maps to `ws`.

### Environment Variables (Synapsis Backend)

| Variable       | Default | Description                                               |
|---------------|---------|-----------------------------------------------------------|
| `PORT`        | `7777`  | Port the FastAPI server listens on (auto-finds if taken)  |
| `CORS_ORIGINS`| `*`     | Comma-separated list of allowed origins, or `*` for all   |

### Frontend Environment Variables

| Variable             | Example                                     | Description                     |
|---------------------|---------------------------------------------|---------------------------------|
| `VITE_SYNAPSIS_URL` | `https://synaptic.synapsis-analytics.com`   | Base URL of the Synapsis server |

### Finding the Server URL

**Production:** The server is publicly available at `https://synaptic.synapsis-analytics.com`. No discovery needed.

**Local development:** If you are running the backend locally, the port is printed in the startup logs:

```bash
# The port is printed in the Synapsis startup logs, e.g.:
# INFO:     Uvicorn running on http://0.0.0.0:7777
```

---

## 9. Common Patterns

### Pattern 1: TV / Kiosk Controller (Command Buttons via REST)

A grid of buttons that each send a predefined command to the `computer_use` agent.

```tsx
import { queryAgent } from "../lib/synapsis-api";
import { useState } from "react";

const COMMANDS = [
  { label: "Open YouTube",     message: "Open YouTube in Safari" },
  { label: "Volume Up",        message: "Press the volume up key 5 times" },
  { label: "Volume Down",      message: "Press the volume down key 5 times" },
  { label: "Mute",             message: "Press the mute key" },
  { label: "Play/Pause",       message: "Press the space bar to play or pause" },
  { label: "Fullscreen",       message: "Press Cmd+F to toggle fullscreen" },
  { label: "Screenshot",       message: "Take a screenshot and save it to /Users/smithai/workspace/outputs/screenshot.png" },
  { label: "Close Window",     message: "Press Cmd+W to close the current window" },
];

export function TVRemote() {
  const [status, setStatus] = useState<string>("Ready");
  const [busy, setBusy] = useState(false);

  const handleCommand = async (message: string) => {
    setBusy(true);
    setStatus("Sending...");
    try {
      const res = await queryAgent("computer_use", { message });
      setStatus(`Done: ${res.response.slice(0, 100)}`);
    } catch (err) {
      setStatus(`Error: ${err}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>TV Remote</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, maxWidth: 400 }}>
        {COMMANDS.map((cmd) => (
          <button
            key={cmd.label}
            onClick={() => handleCommand(cmd.message)}
            disabled={busy}
            style={{
              padding: "20px 10px",
              fontSize: 16,
              borderRadius: 8,
              border: "none",
              background: busy ? "#ccc" : "#333",
              color: "#fff",
              cursor: busy ? "wait" : "pointer",
            }}
          >
            {cmd.label}
          </button>
        ))}
      </div>
      <p style={{ marginTop: 16, color: "#666" }}>{status}</p>
    </div>
  );
}
```

### Pattern 2: File Processor (Upload, Process, Download)

Upload a file, send it to an agent, and present a download link.

```tsx
import { useState } from "react";
import { uploadFile, queryAgent, getFileUrl, type UploadResponse } from "../lib/synapsis-api";

export function FileProcessor() {
  const [status, setStatus] = useState("idle");
  const [outputPath, setOutputPath] = useState<string | null>(null);
  const [response, setResponse] = useState<string>("");

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      // Step 1: Upload
      setStatus("Uploading...");
      const upload = await uploadFile(file);

      // Step 2: Process
      setStatus("Processing...");
      const result = await queryAgent("data_analysis", {
        message: `[Attached files]\n  ${file.name} -> ${upload.path}\n[End attached files]\n\nAnalyze this file. Create a summary report and save it as an Excel file at /Users/smithai/workspace/outputs/report.xlsx`,
      });
      setResponse(result.response);

      // Step 3: Offer download
      setOutputPath("outputs/report.xlsx");
      setStatus("done");
    } catch (err) {
      setStatus("error");
      setResponse(String(err));
    }
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>File Processor</h2>
      <input type="file" accept=".xlsx,.csv" onChange={handleFile} />
      <p>Status: {status}</p>
      {response && <pre style={{ whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto" }}>{response}</pre>}
      {outputPath && (
        <a href={getFileUrl(outputPath)} download style={{ display: "inline-block", marginTop: 10, padding: "10px 20px", background: "#0066cc", color: "#fff", borderRadius: 6, textDecoration: "none" }}>
          Download Report
        </a>
      )}
    </div>
  );
}
```

### Pattern 3: Conversational Assistant (WebSocket Streaming)

A simple streaming chat using the hook from Section 6.4.

```tsx
import { AgentChat } from "../components/AgentChat";

export function ConversationalAssistant() {
  return (
    <div style={{ height: "100vh" }}>
      <AgentChat agentId="data_analysis" />
    </div>
  );
}
```

### Pattern 4: Agent with Custom Instructions Per Query

Use `extra_instructions` to customize agent behavior per query without changing the agent definition.

```tsx
import { queryAgent } from "../lib/synapsis-api";

// Same agent, different behavior depending on context
async function analyzeForExecutive(message: string) {
  return queryAgent("data_analysis", {
    message,
    extra_instructions: "Format your response as an executive summary. Use bullet points. No code. Keep it under 200 words.",
  });
}

async function analyzeForEngineer(message: string) {
  return queryAgent("data_analysis", {
    message,
    extra_instructions: "Include all statistical details. Show your code. Use proper statistical notation.",
  });
}
```

### Pattern 5: Polling for Server Availability

Useful for apps that start before the backend is ready.

```typescript
async function waitForServer(baseUrl: string, maxAttempts = 30, intervalMs = 2000): Promise<boolean> {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetch(`${baseUrl}/api/agents`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return true;
    } catch {
      // Server not ready yet
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}
```

---

## 10. Troubleshooting

### Connection Refused

**Symptom:** `fetch` or WebSocket throws a connection error.

**Causes and fixes:**
- The Synapsis server is not running. Start it on the Mac Mini.
- If using the production URL (`https://synaptic.synapsis-analytics.com`), the reverse proxy or backend may be down. Try `curl https://synaptic.synapsis-analytics.com/api/agents` to verify.
- If using local development (`http://localhost:7777`), check the Synapsis startup logs for the actual port.
- Firewall blocking the port (local dev only). On macOS, check System Settings > Network > Firewall.

### CORS Errors

**Symptom:** Browser console shows `Access-Control-Allow-Origin` errors.

**Causes and fixes:**
- The Synapsis server's `CORS_ORIGINS` env var does not include your app's origin.
- **Quick fix:** Set `CORS_ORIGINS=*` (the default).
- **Proper fix:** Add your app's origin to the list: `CORS_ORIGINS=https://my-mini-app.vercel.app`.
- If using Option B (Vite proxy), CORS is not needed because all requests go through the proxy on the same origin.

### WebSocket Closes Immediately

**Symptom:** WebSocket connects and then closes right away.

**Causes and fixes:**
- Invalid `agent_id`. Verify the agent exists via `GET /api/agents`.
- Network instability. Check Wi-Fi signal.
- Server restarted. Implement reconnection logic (the hook in Section 6.4 provides a `reconnect` method).

### Agent Returns Error

**Symptom:** REST endpoint returns HTTP 4xx/5xx or WebSocket sends `{"type": "error", ...}`.

**Causes and fixes:**
- `404`: Agent ID not found. Check the spelling and use `GET /api/agents` to list valid IDs.
- `422`: Malformed request body. Ensure `Content-Type: application/json` is set and the body is valid JSON with a `message` field.
- `500`: Server-side error. Check the Synapsis backend logs on the Mac.

### File Upload Fails

**Symptom:** `POST /api/upload` returns an error.

**Causes and fixes:**
- Missing `Content-Type: multipart/form-data`. When using `FormData`, do not set `Content-Type` manually -- the browser sets it automatically with the correct boundary.
- File too large. Check if the server has a file size limit configured.
- Disk full on the Mac.

### Agent Cannot Find Uploaded File

**Symptom:** Agent says "file not found" even though upload succeeded.

**Causes and fixes:**
- You did not include the file path in the message. Use the `[Attached files]` format described in Section 5.2.
- You used the original filename instead of the full path returned by the upload endpoint.

### Slow Responses

**Symptom:** REST queries take a long time (minutes).

**This is expected for complex tasks.** Agents may run multiple tool calls (executing Python scripts, reading files, searching the web). Consider:
- Using WebSocket for streaming so the user sees progress.
- Adding `extra_instructions` to request simpler/faster approaches.
- Using a `_sonnet_efficient` variant of the agent for faster but less thorough responses.

### WebSocket Messages Out of Order

**Symptom:** Text chunks seem garbled or out of order.

**This should not happen** since WebSocket guarantees ordered delivery. If you see this:
- Check that you are concatenating (appending) `text` chunks, not replacing.
- Ensure you are not processing messages from multiple WebSocket connections in the same state.

---

## 11. API Type Definitions

Complete TypeScript type definitions for all request and response types. Copy this file into your project as `src/types/synapsis.ts`.

```typescript
// src/types/synapsis.ts
//
// Complete TypeScript type definitions for the Synapsis API.
// These types cover all REST endpoints and WebSocket messages.

// ===================================================================
// Agent Types
// ===================================================================

/** A registered agent in the Synapsis system. */
export interface Agent {
  /** Unique identifier, e.g. "data_analysis", "computer_use". */
  id: string;
  /** Human-readable name, e.g. "Data Analysis". */
  name: string;
  /** Description of the agent's capabilities. */
  description: string;
  /** Whether the agent is builtin or user-created. */
  type: "builtin" | "custom";
  /** List of tool names the agent can use. */
  tools: string[];
  /** Model variant: "opus", "sonnet", etc. */
  model: string;
  /** The agent's system prompt (only included in single-agent detail responses). */
  system_prompt?: string;
}

/** Response from GET /api/agents */
export interface AgentListResponse {
  agents: Agent[];
}

// ===================================================================
// Query Types (REST)
// ===================================================================

/** Request body for POST /api/agents/{agent_id}/query and POST /api/query */
export interface QueryRequest {
  /** The user's message or instruction. */
  message: string;
  /** Optional additional instructions appended to the system prompt for this query only. */
  extra_instructions?: string;
}

/** A record of a tool invocation during agent processing. */
export interface ToolUse {
  /** The tool name, e.g. "Bash", "Read", "Write", "WebSearch". */
  tool: string;
  /** The input parameters passed to the tool. Structure varies by tool. */
  input: Record<string, unknown>;
}

/** Metadata about a completed query. */
export interface QueryResult {
  /** Estimated API cost in USD. */
  estimated_cost: number;
  /** Number of agentic turns (tool call cycles) used. */
  turns: number;
  /** Total wall-clock duration in milliseconds. */
  duration_ms: number;
}

/** Response from POST /api/agents/{agent_id}/query and POST /api/query */
export interface AgentQueryResponse {
  /** The agent's complete text response (Markdown formatted). */
  response: string;
  /** List of tools the agent invoked during processing. */
  tool_uses: ToolUse[];
  /** Metadata about the query execution. */
  result: QueryResult;
  /** ID of the agent that handled the request. */
  agent_id: string;
  /** Human-readable name of the agent. */
  agent_name: string;
}

// ===================================================================
// File Types
// ===================================================================

/** Response from POST /api/upload */
export interface UploadResponse {
  /** Absolute path where the file was saved on the server. */
  path: string;
  /** File size in bytes. */
  size: number;
}

// ===================================================================
// WebSocket Message Types
// ===================================================================

// --- Client to Server ---

/** Client sends a query to the agent. */
export interface WsClientQuery {
  /** The user's message. */
  message: string;
  /** Optional extra instructions for this query. */
  extra_instructions?: string;
}

/** Client requests cancellation of the current query. */
export interface WsClientCancel {
  type: "cancel";
}

/** Union of all messages a client can send over WebSocket. */
export type WsClientMessage = WsClientQuery | WsClientCancel;

// --- Server to Client ---

/** Sent once immediately after WebSocket connection is established. */
export interface WsAgentInfo {
  type: "agent_info";
  agent_id: string;
  agent_name: string;
}

/** A chunk of the agent's streaming text response. Concatenate all chunks in order. */
export interface WsText {
  type: "text";
  /** Partial text content. Append to previous chunks. */
  content: string;
}

/** A block of the agent's internal reasoning. May be shown or hidden in UI. */
export interface WsThinking {
  type: "thinking";
  content: string;
}

/** Early indicator that the agent is preparing a tool call. Arrives before tool_use. */
export interface WsToolGenerating {
  type: "tool_generating";
  /** Tool name, e.g. "Bash", "Read". */
  tool: string;
  /** Unique identifier for this tool invocation. */
  tool_use_id: string;
}

/** Streaming partial JSON as the agent constructs tool input. Optional to handle. */
export interface WsToolInputDelta {
  type: "tool_input_delta";
  /** Partial JSON chunk of the tool input being constructed. */
  content: string;
}

/** The agent is invoking a tool. Complete tool call with all parameters. */
export interface WsToolUse {
  type: "tool_use";
  /** Tool name, e.g. "Bash", "Read". */
  tool: string;
  /** Tool input parameters. */
  input: Record<string, unknown>;
  /** Unique identifier to correlate with the corresponding tool_result. */
  tool_use_id: string;
}

/** The result of a tool invocation. */
export interface WsToolResult {
  type: "tool_result";
  /** Matches the tool_use_id from the corresponding tool_use message. */
  tool_use_id: string;
  /** The tool's output (text, truncated to 8000 chars). */
  content: string;
  /** Whether the tool execution resulted in an error. */
  is_error: boolean;
}

/** Internal SDK lifecycle event. Most frontends can ignore. */
export interface WsSystem {
  type: "system";
  /** Event subtype, e.g. "init", "task_notification". */
  subtype: string;
  /** JSON-encoded event data, or null. */
  data: string | null;
}

/** Final metadata sent when the agent finishes processing a query. Marks end of turn. */
export interface WsResult {
  type: "result";
  estimated_cost: number;
  turns: number;
  duration_ms: number;
  /** Claude SDK session ID (can be used for debugging). */
  session_id?: string;
}

/** Confirms that a cancellation request was processed. */
export interface WsCancelled {
  type: "cancelled";
}

/** An error occurred during processing. */
export interface WsError {
  type: "error";
  message: string;
}

/** Union of all messages the server can send over WebSocket. */
export type WsServerMessage =
  | WsAgentInfo
  | WsText
  | WsThinking
  | WsToolGenerating
  | WsToolInputDelta
  | WsToolUse
  | WsToolResult
  | WsSystem
  | WsResult
  | WsCancelled
  | WsError;

// ===================================================================
// Builtin Agent IDs (Constants)
// ===================================================================

/** Known builtin agent IDs. Custom agents will have user-defined IDs. */
export type BuiltinAgentId =
  | "data_analysis"
  | "visualization_reporting"
  | "research_methodology"
  | "code_automation"
  | "computer_use"
  | "orchestrator"
  | "data_analysis_opus_powerful"
  | "data_analysis_sonnet_efficient"
  | "visualization_reporting_opus_powerful"
  | "visualization_reporting_sonnet_efficient"
  | "research_methodology_opus_powerful"
  | "research_methodology_sonnet_efficient"
  | "code_automation_opus_powerful"
  | "code_automation_sonnet_efficient"
  | "computer_use_opus_powerful"
  | "computer_use_sonnet_efficient";

// ===================================================================
// Builtin Agent Reference Table
// ===================================================================
//
// | Agent ID                   | Name                      | Specialty                                    | Key Tools                              |
// |---------------------------|---------------------------|----------------------------------------------|----------------------------------------|
// | data_analysis             | Data Analysis             | EDA, hypothesis testing, regression,         | Read, Write, Edit, Bash, Glob, Grep,  |
// |                           |                           | time series                                  | WebSearch, WebFetch                    |
// | visualization_reporting   | Visualization & Reporting | Charts, dashboards, HTML reports             | (same as above)                        |
// | research_methodology      | Research Methodology      | Study design, sampling, power analysis       | (same as above)                        |
// | code_automation           | Code & Automation         | ETL, web scraping, API integration, scripts  | (same as above)                        |
// | computer_use              | Computer Use              | GUI interaction, browsers, screenshots       | Bash, mcp__synapsis__computer          |
// | orchestrator              | Orchestrator              | Routes to all other agents                   | All tools + Task                       |
//
// Each agent also has _opus_powerful and _sonnet_efficient variants.
// Custom agents created via the UI or API are also available.
// Always call GET /api/agents to get the current list.

// ===================================================================
// Tool Input Types (Common Tools)
// ===================================================================

/** Input for the Bash tool. */
export interface BashToolInput {
  command: string;
  description?: string;
  timeout?: number;
}

/** Input for the Read tool. */
export interface ReadToolInput {
  file_path: string;
  offset?: number;
  limit?: number;
}

/** Input for the Write tool. */
export interface WriteToolInput {
  file_path: string;
  content: string;
}

/** Input for the Edit tool. */
export interface EditToolInput {
  file_path: string;
  old_string: string;
  new_string: string;
  replace_all?: boolean;
}

/** Input for the Glob tool. */
export interface GlobToolInput {
  pattern: string;
  path?: string;
}

/** Input for the Grep tool. */
export interface GrepToolInput {
  pattern: string;
  path?: string;
  glob?: string;
  output_mode?: "content" | "files_with_matches" | "count";
}

/** Input for the WebSearch tool. */
export interface WebSearchToolInput {
  query: string;
  allowed_domains?: string[];
  blocked_domains?: string[];
}

/** Input for the WebFetch tool. */
export interface WebFetchToolInput {
  url: string;
  prompt: string;
}
```

---

## Appendix: Quick Reference Card

```
BASE_URL = https://synaptic.synapsis-analytics.com    (production)
BASE_URL = http://localhost:7777                       (local dev)

List agents:           GET  {BASE_URL}/api/agents
Agent details:         GET  {BASE_URL}/api/agents/{id}
Query agent (REST):    POST {BASE_URL}/api/agents/{id}/query   { "message": "..." }
Query orchestrator:    POST {BASE_URL}/api/query                { "message": "..." }
Stream agent (WSS):    WSS  wss://synaptic.synapsis-analytics.com/ws/agent/{id}
Stream orchestrator:   WSS  wss://synaptic.synapsis-analytics.com/ws/chat
Upload file:           POST {BASE_URL}/api/upload               multipart/form-data
Download file:         GET  {BASE_URL}/api/files/{relative_path}

Auth: None
CORS: * (default)
```
