# CGIAR Innovation Analytics Platform — Integration Guide

> **Version:** 1.0 | **Last Updated:** 2026-05-22  
> **Environment:** Development (AWS eu-central-1)  
> **Audience:** Developers integrating the platform into CG Insights or other CGIAR web applications.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Option 1: iframe Embedding](#2-option-1-iframe-embedding)
3. [Option 2: REST API Integration](#3-option-2-rest-api-integration)
4. [Option 3: WebSocket Chat Integration](#4-option-3-websocket-chat-integration)
5. [OpenAPI Documentation](#5-openapi-documentation)
6. [Environment and Deployment](#6-environment-and-deployment)
7. [Pending Items and Roadmap](#7-pending-items-and-roadmap)

---

## 1. Overview

The CGIAR Innovation Analytics Platform provides AI-powered analysis of CGIAR's research portfolio, drawing on the PRMS (Planning, Reporting, and Monitoring System) database covering 27,800+ results, 4,600+ innovations, and 183 countries. It exposes a full web interface (React SPA), a REST API, and WebSocket endpoints for real-time AI chat.

This guide covers three ways to integrate the platform into external systems:

| Approach | Effort | Use Case |
|----------|--------|----------|
| **iframe embed** | Minimal | Drop the full UI into an existing page |
| **REST API** | Moderate | Pull KPI data into external dashboards, run one-shot queries |
| **WebSocket chat** | Advanced | Build a custom real-time AI chat widget |

**Current development endpoint:**

```
https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com
```

All examples in this guide use this endpoint. Replace it with the production URL when available.

---

## 2. Option 1: iframe Embedding

The simplest integration. The platform serves a complete React single-page application with a dashboard, AI chat, and visualization capabilities. Embed the entire interface in an iframe.

### Basic Example

```html
<iframe
  src="https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com"
  width="100%"
  height="800"
  style="border: none; border-radius: 8px;"
  allow="clipboard-write"
  title="CGIAR Innovation Analytics"
></iframe>
```

### Responsive Example

For a container that fills its parent element:

```html
<div style="position: relative; width: 100%; height: 0; padding-bottom: 75%; overflow: hidden;">
  <iframe
    src="https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com"
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;"
    allow="clipboard-write"
    title="CGIAR Innovation Analytics"
  ></iframe>
</div>
```

Or, if the embedding page uses a flexbox or grid layout, set the iframe to fill available space:

```css
.analytics-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px); /* subtract your header height */
}

.analytics-container iframe {
  flex: 1;
  width: 100%;
  border: none;
}
```

### CORS and Framing

The development environment is configured with permissive CORS (`Access-Control-Allow-Origin` reflects the requesting origin). No `X-Frame-Options` or `Content-Security-Policy frame-ancestors` headers are set, so the page can be embedded from any origin in the dev environment.

In production, framing will be restricted to approved CGIAR domains.

### Limitations

- **No deep linking.** The SPA currently loads at the root URL. You cannot link directly into a specific view or pre-fill a query via URL parameters. Deep linking support is on the roadmap.
- **Session isolation.** Each iframe maintains its own independent session. A user with the platform open in a separate tab and inside an iframe will have two separate chat histories.
- **Sizing.** The SPA is responsive and works well from approximately 375px wide (mobile) up to full desktop width. For chat-heavy use, a minimum height of 700px is recommended.

---

## 3. Option 2: REST API Integration

For programmatic access to data and AI capabilities without embedding the full UI.

### Base URL

```
https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/api
```

### Key Endpoints for Integration

#### Health Check

```
GET /api/health
```

Returns server status, model information, and version. Useful for monitoring.

```json
{
  "status": "ok",
  "model": "claude-opus-4-6",
  "workspace": "/workspace",
  "auth_method": "api_key",
  "version": "2.0.0"
}
```

#### PRMS Dashboard Statistics

```
GET /api/dashboard/prms-stats
```

Returns KPIs and chart-ready data from the PRMS database. This is the primary endpoint for pulling portfolio metrics into external dashboards. Responses are cached in-memory for 5 minutes.

**Response structure:**

```json
{
  "kpis": {
    "total_results": 27803,
    "total_innovations": 4664,
    "innovation_uses": 559,
    "active_initiatives": 55,
    "countries_covered": 183,
    "knowledge_products": 12850
  },
  "charts": [
    {
      "chartType": "pie",
      "title": "Results by Type",
      "description": "Distribution of results across categories",
      "xAxisKey": "type",
      "data": [
        {"type": "Innovation", "count": 4664},
        {"type": "Knowledge Product", "count": 12850}
      ],
      "series": [
        {"dataKey": "count", "color": "#4F46E5"}
      ]
    }
  ]
}
```

Each entry in `charts` includes `chartType` (pie, bar), `title`, `description`, `xAxisKey`, a `data` array, and a `series` array with color values. The format is designed for direct use with charting libraries such as Recharts, Chart.js, or D3.

**JavaScript example — fetch and display KPIs:**

```javascript
const BASE_URL = 'https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com';

async function fetchPRMSStats() {
  const response = await fetch(`${BASE_URL}/api/dashboard/prms-stats`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();

  console.log(`Total innovations: ${data.kpis.total_innovations}`);  // 4664
  console.log(`Countries covered: ${data.kpis.countries_covered}`);  // 183
  console.log(`Active initiatives: ${data.kpis.active_initiatives}`); // 55

  // Chart data is ready for Recharts / Chart.js
  for (const chart of data.charts) {
    console.log(`${chart.title} (${chart.chartType}): ${chart.data.length} data points`);
  }

  return data;
}
```

#### Stateless Query

```
POST /api/query
```

Send a natural-language question and receive a complete AI response in a single request-response cycle. No WebSocket connection required. Suitable for server-to-server integrations or simple search features.

**Request body:**

```json
{
  "message": "How many innovations does CGIAR have in East Africa?"
}
```

**Response:**

```json
{
  "response": "Based on the PRMS database, CGIAR has documented 847 innovations...",
  "session_id": "abc123",
  "estimated_cost": 0.04,
  "turns": 2
}
```

**JavaScript example:**

```javascript
async function queryPlatform(question) {
  const response = await fetch(`${BASE_URL}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: question })
  });
  const data = await response.json();
  return data.response;
}

// Usage
const answer = await queryPlatform('What are the top 5 countries by innovation count?');
```

Note: This endpoint blocks until the AI completes its response, which can take 10-30 seconds for complex queries that involve database lookups and analysis. For a streaming experience, use the WebSocket integration described in the next section.

#### List Agents

```
GET /api/agents
```

Returns the available specialist agents. Each agent has a different focus area.

```json
{
  "agents": [
    {
      "id": "prms_data_analyst",
      "name": "PRMS Data Analyst",
      "description": "Specialist in querying the PRMS database..."
    },
    {
      "id": "innovation_strategy_advisor",
      "name": "Innovation Strategy Advisor",
      "description": "Strategic analysis of innovation portfolios..."
    }
  ]
}
```

Key agents for CGIAR integration:

| Agent ID | Focus |
|----------|-------|
| `prms_data_analyst` | SQL queries against PRMS, data visualization |
| `innovation_strategy_advisor` | Portfolio strategy, scenario modeling |
| `research_synthesizer` | Cross-initiative pattern analysis |
| `report_generator` | Formatted reports from analysis results |

#### Additional Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Full platform configuration (model, agents, version) |
| `GET` | `/api/sessions` | List chat sessions |
| `GET` | `/api/history` | Get message history for a session |
| `POST` | `/api/upload` | Upload a file for agent processing |
| `GET` | `/api/files` | List uploaded files |
| `POST` | `/api/export/{session_id}` | Export a session as MD, HTML, DOCX, or PDF |
| `GET` | `/api/search` | Full-text search across conversations |
| `GET` | `/api/dashboard/stats` | General usage statistics |

### CORS

The development environment allows all origins. Requests with credentials are supported (the server reflects the request `Origin` header in `Access-Control-Allow-Origin` rather than using a literal `*`).

```javascript
// Credentials are supported if needed
const response = await fetch(`${BASE_URL}/api/dashboard/prms-stats`, {
  credentials: 'include'  // optional — works with or without
});
```

### Error Handling

All endpoints return standard HTTP status codes. Error responses use a consistent format:

```json
{
  "detail": "Description of what went wrong"
}
```

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Bad request (malformed input) |
| 404 | Endpoint or resource not found |
| 422 | Validation error (missing or invalid fields) |
| 500 | Internal server error |

---

## 4. Option 3: WebSocket Chat Integration

For building a custom chat widget with real-time streaming responses, tool execution visibility, and session management.

### Connection

```
wss://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/ws/chat
```

WebSocket connections bypass CORS middleware entirely (this is standard browser behavior — the WebSocket handshake does not use CORS preflight).

### Minimal Working Example

```javascript
const WS_URL = 'wss://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/ws/chat';

function connectChat() {
  const ws = new WebSocket(WS_URL);
  let responseText = '';

  ws.onopen = () => {
    console.log('Connected to CGIAR Innovation Analytics');
    // Send a question
    ws.send(JSON.stringify({
      message: 'How many innovations does CGIAR have?'
    }));
  };

  ws.onmessage = (event) => {
    const frame = JSON.parse(event.data);

    switch (frame.type) {
      case 'text':
        // Streaming content — append to display
        responseText += frame.content;
        updateChatUI(responseText);
        break;

      case 'thinking':
        // Model reasoning (optional to display)
        showThinkingIndicator(frame.content);
        break;

      case 'tool_use':
        // Agent is calling a tool (e.g., querying the PRMS database)
        showToolActivity(`Using tool: ${frame.tool}`);
        break;

      case 'tool_result':
        // Tool returned a result
        hideToolActivity();
        break;

      case 'result':
        // Response complete
        console.log(`Done. Cost: $${frame.estimated_cost}, Turns: ${frame.turns}`);
        break;

      case 'error':
        console.error('Error:', frame.message);
        break;

      case 'session':
        // Session ID assigned — store for reconnection
        console.log('Session:', frame.session_id);
        break;
    }
  };

  ws.onclose = (event) => {
    console.log(`Disconnected: code=${event.code}, reason=${event.reason}`);
  };

  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };

  return ws;
}
```

### Client-to-Server Messages

#### Send a Chat Message

```json
{
  "message": "What are the top innovations in Kenya?"
}
```

#### Cancel an In-Progress Response

```json
{
  "type": "cancel"
}
```

#### Start a New Session

```json
{
  "type": "new_session"
}
```

#### Switch to an Existing Session

```json
{
  "type": "switch_session",
  "session_id": "existing-session-id"
}
```

#### Retry with a Different Model

```json
{
  "type": "retry_with_model",
  "message": "Summarize innovation trends",
  "model": "claude-sonnet-4-5-20250929"
}
```

### Server-to-Client Frame Types

Every frame includes a `session_id` field.

| Type | Description | Key Fields |
|------|-------------|------------|
| `text` | Streaming content chunk | `content` (string) |
| `thinking` | Model reasoning/planning | `content` (string) |
| `tool_use` | Agent invoking a tool | `tool` (name), `input` (object), `tool_use_id` |
| `tool_result` | Tool execution result | `tool_use_id`, `content` (string), `is_error` (boolean) |
| `system` | System notification | `subtype`, `data` |
| `result` | Response complete | `estimated_cost` (number), `turns` (number) |
| `session` | Session ID assignment | `session_id` |
| `cancelled` | Cancellation confirmed | |
| `error` | Error occurred | `message` (string) |

### Full Chat Widget Example

A more complete example showing multi-turn conversation, session persistence, and cancellation:

```javascript
class CGIARChatWidget {
  constructor(containerElement) {
    this.container = containerElement;
    this.ws = null;
    this.sessionId = null;
    this.currentResponse = '';
    this.isStreaming = false;
  }

  connect() {
    this.ws = new WebSocket(
      'wss://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/ws/chat'
    );

    this.ws.onopen = () => {
      this.setStatus('connected');
      // Resume previous session if we have one
      if (this.sessionId) {
        this.ws.send(JSON.stringify({
          type: 'switch_session',
          session_id: this.sessionId
        }));
      }
    };

    this.ws.onmessage = (event) => this.handleFrame(JSON.parse(event.data));

    this.ws.onclose = () => {
      this.setStatus('disconnected');
      // Reconnect after 3 seconds
      setTimeout(() => this.connect(), 3000);
    };
  }

  handleFrame(frame) {
    switch (frame.type) {
      case 'session':
        this.sessionId = frame.session_id;
        break;
      case 'text':
        this.currentResponse += frame.content;
        this.renderResponse(this.currentResponse);
        break;
      case 'tool_use':
        this.renderToolCall(frame.tool, frame.input);
        break;
      case 'tool_result':
        this.renderToolResult(frame.tool_use_id, frame.content, frame.is_error);
        break;
      case 'result':
        this.isStreaming = false;
        this.finalizeResponse(frame);
        this.currentResponse = '';
        break;
      case 'error':
        this.renderError(frame.message);
        this.isStreaming = false;
        break;
    }
  }

  send(message) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('Not connected');
      return;
    }
    this.isStreaming = true;
    this.currentResponse = '';
    this.renderUserMessage(message);
    this.ws.send(JSON.stringify({ message }));
  }

  cancel() {
    if (this.isStreaming && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'cancel' }));
    }
  }

  newSession() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'new_session' }));
      this.sessionId = null;
      this.clearChat();
    }
  }

  // Implement these rendering methods for your UI framework:
  setStatus(status) { /* ... */ }
  renderUserMessage(text) { /* ... */ }
  renderResponse(text) { /* ... */ }
  renderToolCall(tool, input) { /* ... */ }
  renderToolResult(id, content, isError) { /* ... */ }
  finalizeResponse(result) { /* ... */ }
  renderError(message) { /* ... */ }
  clearChat() { /* ... */ }
}

// Usage
const widget = new CGIARChatWidget(document.getElementById('chat-container'));
widget.connect();
widget.send('Show me innovation trends in Sub-Saharan Africa');
```

### Specialized WebSocket Endpoints

In addition to the general chat endpoint, the platform offers direct connections to specific agents and multi-agent workflows:

| Endpoint | Description |
|----------|-------------|
| `wss://<host>/ws/agent/{agent_id}` | Direct interaction with a specific agent (e.g., `prms_data_analyst`) |
| `wss://<host>/ws/workflow/{workflow_id}` | Streaming execution of a predefined workflow |
| `wss://<host>/ws/fleet/{fleet_id}` | Multi-agent team execution with streaming |

These follow the same frame protocol as `/ws/chat`.

---

## 5. OpenAPI Documentation

The platform includes auto-generated interactive API documentation.

| Resource | URL |
|----------|-----|
| **Swagger UI** | [/docs](https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/docs) |
| **ReDoc** | [/redoc](https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/redoc) |
| **OpenAPI JSON** | [/openapi.json](https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/openapi.json) |

The Swagger UI at `/docs` allows you to try endpoints directly from the browser — useful for exploring the API before writing integration code.

To generate a typed client from the OpenAPI schema:

```bash
# Download the schema
curl -o openapi.json https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/openapi.json

# Generate a TypeScript client (using openapi-typescript-codegen)
npx openapi-typescript-codegen --input openapi.json --output ./generated-client
```

---

## 6. Environment and Deployment

### Current Infrastructure

| Component | Detail |
|-----------|--------|
| **Environment** | Development |
| **Region** | AWS eu-central-1 (Frankfurt) |
| **Compute** | EC2 t3.large |
| **Load Balancer** | Application Load Balancer (ALB) with TLS termination |
| **Container Registry** | Amazon ECR |
| **Infrastructure-as-Code** | AWS CloudFormation |
| **ALB Endpoint** | `https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com` |
| **Custom Domain (pending)** | `innovation-analytics-dev.synapsis-analytics.com` |
| **Container Port** | 7780 (internal), 443 via ALB |

### Architecture Diagram

```
                           Internet
                              |
                              v
                    +-------------------+
                    |  AWS ALB (443)    |
                    |  TLS termination  |
                    +-------------------+
                              |
                              v
                    +-------------------+
                    |  EC2 (t3.large)   |
                    |  Docker container |
                    |  Port 7780        |
                    |                   |
                    |  FastAPI backend  |
                    |  React SPA        |
                    |  Claude AI agents |
                    |  PRMS SQLite DB   |
                    +-------------------+
```

### CI/CD

The platform deploys through GitHub Actions with OIDC-authenticated AWS roles. Code is pushed to the `cgiar-ppu/cgiar-innovation-analytics` repository. Branch-based deployments follow the standard pipeline:

- `develop` branch deploys to the DEV environment
- `staging` branch deploys to TST
- `main` branch deploys to PRD

---

## 7. Pending Items and Roadmap

These items are planned but not yet implemented. Factor them into your integration design.

### Authentication

**Status:** Not implemented.

The platform currently has no client-side authentication for the web interface. The backend uses an API key for Anthropic model access, but external callers do not need to authenticate.

**Plan:** AWS Cognito integration will add:
- JWT bearer tokens for API access (pass in `Authorization: Bearer <token>` header)
- SSO support for the web interface (SAML/OIDC federation with CGIAR identity providers)
- Token-scoped permissions per integration client

**Impact on integrations:** When authentication is added, all API calls and WebSocket connections will require a valid token. iframe embeds will redirect to a login page unless the user is already authenticated. Plan for token acquisition and refresh in your integration code.

### DNS

**Status:** Pending.

A custom domain (`innovation-analytics-dev.synapsis-analytics.com`) is ready except for the DNS record. The ACM certificate exists and the ALB listener is configured. The delay is due to a cross-account Route53 setup (the hosted zone is in the sandbox account, the ALB is in the dev account).

**Impact on integrations:** When the DNS record is created, the custom domain will work alongside the ALB endpoint. Update your base URLs at that point. The ALB endpoint will continue to work.

### Rate Limiting

**Status:** Not implemented.

There are currently no rate limits on any endpoint. AI queries are the most expensive operation (each `/api/query` call or WebSocket conversation turn invokes the Claude API).

**Plan:** Per-client rate limits will be added, likely using API keys or JWT claims to identify clients. Expected limits will be communicated before enforcement.

**Impact on integrations:** Design your integration to handle HTTP 429 (Too Many Requests) responses gracefully. Implement exponential backoff for retries.

### CORS Lockdown

**Status:** Currently allows all origins.

**Plan:** In production, `Access-Control-Allow-Origin` will be restricted to known CGIAR domains (e.g., CG Insights production URLs). Integration developers will need to register their origin domains.

**Impact on integrations:** Browser-based integrations from unregistered origins will stop working when this is enforced. Server-to-server integrations are unaffected (CORS is a browser-only mechanism).

### Webhook / Callback Support

**Status:** Not available.

**Plan:** An optional webhook mechanism could be added for asynchronous query completion notifications. This would allow a server-side integration to submit a query and receive the result via HTTP callback rather than holding a connection open.

**Impact on integrations:** Not blocking for current use cases. Relevant for server-to-server integrations that cannot maintain WebSocket connections.

### Deep Linking

**Status:** Not available.

**Plan:** URL-based routing to specific views (e.g., `/dashboard`, `/chat?q=...`) would allow iframe embeds and direct links to target specific platform functionality.

**Impact on integrations:** Currently, iframe embeds always load the default landing view. Deep linking will allow richer integration scenarios.

---

*For questions about this integration guide, contact the Synapsis Analytics team or open an issue in the [cgiar-ppu/cgiar-innovation-analytics](https://github.com/cgiar-ppu/cgiar-innovation-analytics) repository.*
