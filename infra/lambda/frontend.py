"""
Synapsis Analytics Agent - Frontend Lambda
Serves the provision/launch page at GET /
"""

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synapsis Analytics — Launch</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e0e0e0;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
  }
  .card {
    background: #1a1d27;
    border: 1px solid #2e3140;
    border-radius: 12px;
    padding: 40px;
    width: 420px;
    max-width: 95vw;
  }
  h1 { color: #2e7d32; font-size: 20px; margin-bottom: 6px; }
  .subtitle { color: #888; font-size: 13px; margin-bottom: 28px; }
  label { display: block; font-size: 13px; color: #aaa; margin-bottom: 6px; }
  input {
    width: 100%;
    padding: 10px 14px;
    background: #12141c;
    border: 1px solid #2e3140;
    border-radius: 8px;
    color: #e0e0e0;
    font-size: 15px;
    outline: none;
    margin-bottom: 18px;
  }
  input:focus { border-color: #2e7d32; }
  button {
    width: 100%;
    padding: 11px;
    background: #2e7d32;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
  }
  button:hover { background: #1b5e20; }
  button:disabled { background: #333; color: #666; cursor: not-allowed; }
  .log {
    margin-top: 24px;
    background: #12141c;
    border: 1px solid #2e3140;
    border-radius: 8px;
    padding: 14px;
    font-family: 'SF Mono', 'Consolas', monospace;
    font-size: 12.5px;
    line-height: 1.7;
    max-height: 300px;
    overflow-y: auto;
    display: none;
  }
  .log .line { margin-bottom: 2px; }
  .log .ts { color: #555; }
  .log .ok { color: #4caf50; }
  .log .warn { color: #ff9800; }
  .log .err { color: #f44336; }
  .log .info { color: #64b5f6; }
  .result {
    margin-top: 18px;
    padding: 16px;
    border-radius: 8px;
    display: none;
    text-align: center;
  }
  .result.success { background: #1b3a1b; border: 1px solid #2e7d32; display: block; }
  .result.error { background: #3a1b1b; border: 1px solid #c62828; display: block; }
  .result a { color: #4caf50; font-size: 18px; font-weight: 600; text-decoration: none; }
  .result a:hover { text-decoration: underline; }
  .result .hint { color: #888; font-size: 12px; margin-top: 8px; }
  .spinner {
    display: inline-block; width: 14px; height: 14px;
    border: 2px solid #555; border-top-color: #4caf50;
    border-radius: 50%; animation: spin 0.8s linear infinite;
    vertical-align: middle; margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <h1>Synapsis Analytics</h1>
  <p class="subtitle">Launch your agent container</p>

  <label for="userId">Your user ID</label>
  <input type="text" id="userId" placeholder="e.g. james" spellcheck="false" autofocus>

  <button id="launchBtn" onclick="launch()">Launch Agent</button>

  <div class="log" id="log"></div>
  <div class="result" id="result"></div>
</div>

<script>
const BASE = window.location.origin;
const logEl = document.getElementById('log');
const resultEl = document.getElementById('result');
const btn = document.getElementById('launchBtn');

function ts() {
  return new Date().toLocaleTimeString('en-GB', { hour12: false });
}
function log(msg, cls = 'info') {
  logEl.style.display = 'block';
  logEl.innerHTML += `<div class="line"><span class="ts">${ts()}</span> <span class="${cls}">${msg}</span></div>`;
  logEl.scrollTop = logEl.scrollHeight;
}
function showResult(html, ok) {
  resultEl.className = 'result ' + (ok ? 'success' : 'error');
  resultEl.innerHTML = html;
  resultEl.style.display = 'block';
}

async function apiFetch(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(`${BASE}${path}`, opts);
  const data = await resp.json();
  return { status: resp.status, data };
}

async function pollStatus(userId, maxAttempts = 60) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 3000));
    try {
      const { status, data } = await apiFetch('GET', `/status/${userId}`);
      if (data.status === 'ready' && data.appUrl) return data;
      log(`Polling... ${data.status || 'waiting'} (${i + 1}/${maxAttempts})`);
    } catch (e) {
      log(`Poll error: ${e.message}`, 'warn');
    }
  }
  return null;
}

async function launch() {
  const userId = document.getElementById('userId').value.trim();
  if (!userId) { document.getElementById('userId').focus(); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Launching...';
  logEl.innerHTML = '';
  logEl.style.display = 'block';
  resultEl.style.display = 'none';

  log(`Requesting container for <b>${userId}</b>...`);

  try {
    const { status, data } = await apiFetch('POST', '/provision', { userId });

    if (status === 200 && data.status === 'ready') {
      log('Container ready!', 'ok');
      showResult(
        `<a href="${data.appUrl}" target="_blank">${data.appUrl}</a>` +
        `<div class="hint">Click to open your agent${data.coldStart ? ' (fresh instance)' : ''}</div>`,
        true
      );
    } else if (status === 202 || data.status === 'provisioning') {
      log('Instance is starting up \u2014 polling for readiness...', 'warn');
      const result = await pollStatus(userId);
      if (result && result.appUrl) {
        log('Container ready!', 'ok');
        showResult(
          `<a href="${result.appUrl}" target="_blank">${result.appUrl}</a>` +
          `<div class="hint">Click to open your agent</div>`,
          true
        );
      } else {
        log('Timed out waiting for container', 'err');
        showResult('Provisioning timed out. Try again in a minute.', false);
      }
    } else {
      log(`Error ${status}: ${JSON.stringify(data)}`, 'err');
      showResult(`Error ${status}: ${data.error || data.message || JSON.stringify(data)}`, false);
    }
  } catch (e) {
    log(`Request failed: ${e.message}`, 'err');
    showResult(`Failed to reach API: ${e.message}`, false);
  }

  btn.disabled = false;
  btn.textContent = 'Launch Agent';
}

document.getElementById('userId').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') launch();
});
</script>
</body>
</html>"""


def handler(event, context):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": HTML,
    }
