import { EFFECTS, type Adapter } from './actions';
import { isVoiceDispatch } from '../chatCommands';
import { voicePost } from './http';
import { getAuthToken } from '../../stores/auth';
export type VoiceStatus = 'idle' | 'connecting' | 'connected' | 'closing' | 'error';
export interface Caption { id: string; speaker: 'user' | 'assistant'; delta: string; start: number; end: number }
export interface LiveCallbacks {
  status: (status: VoiceStatus, message: string) => void;
  caption: (caption: Caption) => void;
  task: (message: string) => void;
  playbackBlocked: (blocked: boolean) => void;
  usage: (seconds: number, final: boolean) => void;
  evidence: (result: Record<string, unknown>) => void;
}
type FunctionCall = { call_id: string; name: string; arguments: string };
type Batch = { calls: FunctionCall[]; terminal: boolean; delegation: string; epoch: number; processed: boolean };
type LiveEvent = { type: string; [key: string]: unknown };

/** GPT-Live uses its own events; it is not a Realtime model-name substitution. */
export class LiveClient {
  private peer?: RTCPeerConnection;
  private channel?: RTCDataChannel;
  private microphone?: MediaStream;
  private audio = new Audio();
  private abort?: AbortController;
  private generation = 0;
  private ready = false;
  private closing = false;
  private requestId?: string;
  private authToken: string | null = null;
  private heartbeatTimer?: ReturnType<typeof setInterval>;
  private startTimer?: ReturnType<typeof setTimeout>;
  private closeTimer?: ReturnType<typeof setTimeout>;
  private limitTimer?: ReturnType<typeof setTimeout>;
  private disconnectedTimer?: ReturnType<typeof setTimeout>;
  private seen = new Set<string>();
  private calls = new Map<string, Record<string, unknown>>();
  private batches = new Map<string, Batch>();
  private responseForDelegation = new Map<string, string>();
  private latestDelegation?: string;
  private epoch = 0;
  private actionQueue: Promise<void> = Promise.resolve();
  private paused = false;
  private pendingTyped: string[] = [];
  private typedAwaitingResponse = false;
  private unsubscribers: Array<() => void> = [];
  private contextTimer?: ReturnType<typeof setTimeout>;
  constructor(private cb: LiveCallbacks, private adapter: Adapter) { this.audio.autoplay = true; }

  private send(event: Record<string, unknown>) {
    if (this.channel?.readyState === 'open') this.channel.send(JSON.stringify(event));
  }
  private async closeOnServer(id = this.requestId) {
    if (!id) return;
    try {
      const result = await voicePost(`sessions/${id}/close`, {}, { keepalive: true, token: this.authToken });
      if (!result.closed) this.cb.task('Voice stopped locally. Server cleanup is pending; its retry watchdog remains active.');
    } catch { this.cb.task('Voice stopped locally. Server cleanup could not be confirmed; the heartbeat lease will expire.'); }
  }
  private cleanup() {
    this.ready = false;
    this.unsubscribers.forEach(unsubscribe => unsubscribe()); this.unsubscribers = []; clearTimeout(this.contextTimer);
    clearInterval(this.heartbeatTimer); clearTimeout(this.startTimer); clearTimeout(this.closeTimer); clearTimeout(this.limitTimer); clearTimeout(this.disconnectedTimer);
    this.abort?.abort();
    this.microphone?.getTracks().forEach(track => track.stop()); this.microphone = undefined;
    const peer = this.peer, channel = this.channel; this.peer = undefined; this.channel = undefined;
    channel?.close(); peer?.close(); this.audio.pause(); this.audio.srcObject = null;
    this.pendingTyped = []; this.typedAwaitingResponse = false;
  }
  private fail(message: string) {
    if (this.closing) return;
    this.generation++; this.epoch++;
    void this.closeOnServer(); this.cleanup(); this.cb.status('error', message);
  }
  async start() {
    if (this.peer || this.ready) return;
    const generation = ++this.generation;
    this.closing = false; this.paused = false; this.requestId = undefined; this.authToken = getAuthToken();
    this.actionQueue = Promise.resolve(); this.epoch++;
    this.seen.clear(); this.calls.clear(); this.batches.clear(); this.responseForDelegation.clear(); this.latestDelegation = undefined;
    this.cb.playbackBlocked(false);
    this.cb.status('connecting', 'Checking microphone and connecting…');
    this.abort = new AbortController();
    this.startTimer = setTimeout(() => this.fail('The voice connection timed out. Check your microphone/network and try again.'), 45000);
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access needs localhost or HTTPS in a supported browser.');
      const mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (generation !== this.generation) { mic.getTracks().forEach(track => track.stop()); return; }
      this.microphone = mic;
      const peer = new RTCPeerConnection(); this.peer = peer;
      for (const track of mic.getAudioTracks()) {
        peer.addTrack(track, mic);
        track.addEventListener('ended', () => { if (generation === this.generation && !this.closing) this.fail('Microphone access ended. Reconnect when it is available.'); });
      }
      peer.ontrack = event => {
        if (generation !== this.generation) return;
        this.audio.srcObject = new MediaStream([event.track]); void this.resumePlayback();
      };
      peer.onconnectionstatechange = () => {
        if (generation !== this.generation || this.closing) return;
        if (peer.connectionState === 'failed') this.fail('The audio connection failed. Please reconnect.');
        if (peer.connectionState === 'disconnected') this.disconnectedTimer = setTimeout(() => this.fail('The audio connection was lost. Please reconnect.'), 10000);
        else clearTimeout(this.disconnectedTimer);
      };
      const channel = peer.createDataChannel('oai-events'); this.channel = channel;
      channel.onmessage = event => {
        if (generation !== this.generation) return;
        try { this.onEvent(JSON.parse(event.data)); } catch { this.cb.task('An unexpected voice event was ignored.'); }
      };
      channel.onclose = () => { if (generation === this.generation && this.ready && !this.closing) this.fail('Voice disconnected before final usage was confirmed.'); };
      await peer.setLocalDescription(await peer.createOffer());
      if (peer.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', check); reject(new Error('The browser could not establish an audio route.')); }, 10000);
        const check = () => { if (peer.iceGatheringState === 'complete') { clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', check); resolve(); } };
        peer.addEventListener('icegatheringstatechange', check); check();
      });
      if (generation !== this.generation) return;
      this.requestId = crypto.randomUUID();
      const requestId = this.requestId;
      const result = await voicePost('sessions', { request_id: requestId, sdp: peer.localDescription?.sdp }, { signal: this.abort.signal });
      if (generation !== this.generation) { void this.closeOnServer(requestId); return; }
      this.heartbeatTimer = setInterval(() => {
        void voicePost(`sessions/${requestId}/heartbeat`, {}, { token: this.authToken }).catch(() => {
          if (generation === this.generation && !this.closing) this.fail('Voice authorization or heartbeat was lost. Please reconnect.');
        });
      }, 20000);
      await peer.setRemoteDescription({ type: 'answer', sdp: result.transport.sdp });
      this.limitTimer = setTimeout(() => { this.cb.task('The 10-minute voice session has ended. Start again to continue.'); this.end(); }, Math.max(0, result.expires_at * 1000 - Date.now() - 2000));
    } catch (error) {
      if (generation !== this.generation) return;
      const message = error instanceof DOMException && error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow microphone access in the browser and retry.' : error instanceof Error ? error.message : 'Voice connection failed.';
      this.fail(message);
    }
  }
  async resumePlayback() {
    try { await this.audio.play(); this.cb.playbackBlocked(false); }
    catch { this.cb.playbackBlocked(true); }
  }
  mute(muted: boolean) {
    this.microphone?.getAudioTracks().forEach(track => { track.enabled = !muted; });
    if (this.ready) this.send({ type: muted ? 'session.input_audio.mute' : 'session.input_audio.unmute', event_id: crypto.randomUUID() });
  }
  pauseActions(paused: boolean) {
    this.paused = paused; this.epoch++;
    this.cb.task(paused ? 'App actions paused. Submitted analytics queries may still run.' : 'App actions enabled. Ask again for any cancelled request.');
    if (this.ready) this.send({ type: 'session.instructions.append', delegation_id: null, content: paused ? 'The user paused app actions. Pending actions have been blocked; completed changes remain. Do not claim they were undone. You can still discuss data.' : 'The user re-enabled app actions. Do not replay cancelled work; wait for their next request.' });
  }
  typeMessage(text: string) {
    if (!this.ready || this.closing || !text.trim()) return;
    this.pendingTyped.push(text.trim().slice(0, 2000)); this.flushTyped();
  }
  private flushTyped() {
    if (this.closing || this.typedAwaitingResponse || [...this.batches.values()].some(batch => !batch.processed)) return;
    const text = this.pendingTyped.shift(); if (!text) return;
    this.epoch++;
    this.typedAwaitingResponse = true;
    this.send({ type: 'response.item.create', event_id: crypto.randomUUID(), item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } });
    this.send({ type: 'response.create', event_id: crypto.randomUUID() });
  }
  end() {
    if (this.closing) return;
    this.closing = true; this.epoch++;
    // Stop capturing immediately; keep media connection alive for final usage.
    this.microphone?.getAudioTracks().forEach(track => { track.enabled = false; });
    this.cb.status('closing', 'Ending conversation…');
    if (this.ready && this.channel?.readyState === 'open') {
      this.send({ type: 'session.close', event_id: crypto.randomUUID() });
      this.closeTimer = setTimeout(() => {
        this.generation++; void this.closeOnServer(); this.cleanup(); this.closing = false;
        this.cb.status('idle', 'Ended. Final usage could not be confirmed.');
      }, 8000);
    } else {
      this.generation++; void this.closeOnServer(); this.cleanup(); this.closing = false; this.cb.status('idle', 'Conversation ended.');
    }
  }
  dispose() { this.generation++; this.epoch++; this.closing = true; void this.closeOnServer(); this.cleanup(); }
  contextChanged() {
    if (!this.ready || this.closing) return;
    if (!isVoiceDispatch()) this.epoch++;
    clearTimeout(this.contextTimer);
    this.contextTimer = setTimeout(() => {
      if (this.ready && !this.closing) this.send({ type: 'session.thinking.append', event_id: crypto.randomUUID(), delegation_id: null, content: 'Application state changed. Delegate to read_app for fresh selected chat, filters and query status before answering state-dependent questions. Prior state may be stale.' });
    }, 250);
  }
  private watchApp() {
    this.unsubscribers = [this.adapter.subscribe(() => this.contextChanged())];
  }
  private onEvent(event: LiveEvent) {
    const id = typeof event.event_id === 'string' ? event.event_id : undefined;
    if (id && this.seen.has(id)) return;
    if (id) { this.seen.add(id); if (this.seen.size > 15000) this.seen.delete(this.seen.values().next().value!); }
    if (event.type === 'session.started') {
      if (this.closing) { this.send({ type: 'session.close' }); return; }
      this.ready = true; this.watchApp(); clearTimeout(this.startTimer); this.cb.status('connected', 'Listening · you can interrupt naturally');
      this.send({ type: 'session.instructions.append', event_id: 'ia_greeting', delegation_id: null, content: 'Speak English to begin. Greet the user immediately: introduce yourself as their AI Innovation Analytics guide and invite them to ask how the app works, discuss the data, or control their chats. Then pause and listen. Do not wait for the user to speak first.' });
    } else if (event.type === 'session.instructions.appended' && event.client_event_id === 'ia_greeting' && !this.closing) {
      this.send({ type: 'session.commentary.append', delegation_id: null, content: 'Begin the conversation now, following the greeting instructions.' });
    } else if (event.type === 'session.closed') {
      this.cb.usage(Number((event.usage as { seconds?: number })?.seconds || 0), true);
      this.generation++; this.epoch++; void this.closeOnServer(); this.cleanup(); this.closing = false; this.cb.status('idle', 'Conversation ended.');
    } else if (event.type === 'session.usage.updated') {
      this.cb.usage(Number((event.usage as { seconds?: number })?.seconds || 0), false);
    } else if (event.type === 'session.input_transcript.delta' || event.type === 'session.output_transcript.delta') {
      this.cb.caption({ id: id || crypto.randomUUID(), speaker: event.type === 'session.input_transcript.delta' ? 'user' : 'assistant', delta: String(event.delta ?? ''), start: Number(event.start_ms || 0), end: Number(event.end_ms || 0) });
    } else if (event.type === 'session.delegation.created') {
      const delegation = event.delegation as { id?: string };
      if (delegation?.id) { this.latestDelegation = delegation.id; this.epoch++; }
      this.cb.task('Checking the application…');
    } else if (event.type === 'error') {
      const error = event.error as { message?: string; code?: string } | undefined;
      if (!this.ready) this.fail('The voice service could not start. Please check its configuration.');
      else this.cb.task(`Voice service: ${error?.message || error?.code || 'A command was rejected.'}`);
    } else if (event.type === 'response.event' && !this.closing) {
      const nested = event.event as LiveEvent;
      const delegation = String(event.delegation_id ?? '');
      if (nested.type === 'response.created') {
        this.typedAwaitingResponse = false;
        const response = nested.response as { id: string };
        this.responseForDelegation.set(delegation, response.id);
        this.batches.set(response.id, { calls: [], terminal: false, delegation, epoch: this.epoch, processed: false });
      }
      const response = nested.response as { id?: string } | undefined;
      const responseId = String(nested.response_id ?? response?.id ?? this.responseForDelegation.get(delegation) ?? '');
      const batch = this.batches.get(responseId);
      if (!batch) return;
      if (nested.type === 'response.output_item.done') {
        const item = nested.item as FunctionCall & { type: string };
        if (item?.type === 'function_call' && !batch.calls.some(call => call.call_id === item.call_id)) batch.calls.push(item);
      }
      if (['response.completed', 'response.failed', 'response.incomplete', 'response.cancelled'].includes(nested.type)) {
        batch.terminal = true;
        if (nested.type !== 'response.completed') { batch.processed = true; this.cb.task('Backend work did not complete. Please retry the request.'); this.flushTyped(); return; }
        const generation = this.generation;
        this.actionQueue = this.actionQueue.then(async () => {
          if (generation !== this.generation || this.closing || batch.processed) return;
          batch.processed = true;
          for (const call of batch.calls) {
            if (generation !== this.generation || this.closing) return;
            let result = this.calls.get(call.call_id);
            if (!result) {
              const stale = batch.epoch !== this.epoch || (batch.delegation && this.latestDelegation && batch.delegation !== this.latestDelegation);
              const read = EFFECTS[call.name] === 'read';
              if (stale || (this.paused && !read)) result = { ok: false, cancelled: true, error: 'This action was cancelled or superseded. Read current state and follow only the newest request. Do not replay it.' };
              else {
                this.cb.task(`${call.name.replace(/_/g, ' ')}…`);
                try { result = await this.adapter.execute(call.name, JSON.parse(call.arguments), this.abort!.signal, () => generation === this.generation && !this.closing && batch.epoch === this.epoch && (!this.paused || read)); }
                catch { result = { ok: false, error: 'Invalid tool arguments' }; }
              }
              this.calls.set(call.call_id, result);
            }
            if (generation !== this.generation || this.closing) return;
            this.send({ type: 'response.item.create', event_id: crypto.randomUUID(), item: { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result) } });
            this.cb.task(result.ok ? String(result.effect || 'Information retrieved.') : String(result.error));
            if (result.excerpts || result.messages || result.reporting_phases) this.cb.evidence(result);
          }
          if (batch.calls.length) this.send({ type: 'response.create', event_id: crypto.randomUUID() });
          else { this.cb.task('Ready for your next question.'); this.flushTyped(); }
          // Bound response bookkeeping for long sessions.
          if (this.batches.size > 250) for (const [id, old] of this.batches) { if (old.processed && id !== responseId) { this.batches.delete(id); if (this.batches.size <= 200) break; } }
        }).catch(() => this.cb.task('Could not complete a app action. Please retry.'));
      }
    }
  }
}
