import { EFFECTS, type Adapter, type ToolResult } from './actions';
import { isVoiceDispatch } from '../chatCommands';
import { voicePost, voiceStart } from './http';
import { getAuthToken } from '../../stores/auth';
import type { Caption, LiveCallbacks, VoiceStatus } from './liveClient';

/**
 * GA Realtime protocol client (Azure OpenAI gpt-realtime-mini today; any realtime deployment by config).
 *
 * Same public surface and safety rules as LiveClient (server-minted session, heartbeat lease, 10-minute cap,
 * pause/epoch/stale-action guards, one function_call_output per call), but the Realtime event set:
 * the speech model calls the app tools itself (no delegated backend), tool calls arrive in response.done,
 * outputs go back as conversation.item.create + response.create, and app notices are system messages.
 * The server negotiates the SDP, so neither the API key nor the ephemeral client secret reaches the browser.
 */
type FunctionCall = { call_id: string; name: string; arguments: string };
type Batch = { calls: FunctionCall[]; epoch: number; processed: boolean };
type RealtimeEvent = { type: string; [key: string]: unknown };
export type RealtimeFeedbackPhase = 'idle' | 'asking' | 'saved';
export type RealtimeCallbacks = LiveCallbacks & { feedback?: (phase: RealtimeFeedbackPhase) => void };
/** Stores a 1-5 rating for the voice session (optional: only builds with voice feedback pass it). */
export type RateSession = (requestId: string, rating: number, improvement: string) => Promise<unknown>;
const FEEDBACK_TOOL = 'submit_feedback';
const FEEDBACK_MIN_CALL_MS = 15000, FEEDBACK_MIN_LEFT_MS = 45000, FEEDBACK_WINDOW_MS = 60000, FEEDBACK_GOODBYE_MS = 8000;
const FEEDBACK_INSTRUCTION = 'The user pressed End. Before the call closes, ask ONCE, in one short sentence: "Before you go, would you like to rate this session from 1 to 5 and suggest one improvement?" If they give a rating, repeat it back in a few words, call submit_feedback once, thank them and say goodbye. If they decline, hesitate or say nothing, simply say goodbye. Do not ask again, do not insist and do not start any other work.';
export const GREETING_INSTRUCTION = 'Speak English to begin. Greet the user immediately: introduce yourself as their AI Innovation Analytics guide and invite them to ask how the app works, discuss the data, or control their chats. Then pause and listen. Do not wait for the user to speak first.';

export class RealtimeClient {
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
  private limitTimer?: ReturnType<typeof setTimeout>;
  private disconnectedTimer?: ReturnType<typeof setTimeout>;
  private contextTimer?: ReturnType<typeof setTimeout>;
  private feedbackTimer?: ReturnType<typeof setTimeout>;
  private seen = new Set<string>();
  private calls = new Map<string, ToolResult>();
  private batches = new Map<string, Batch>();
  private transcribed = new Set<string>();
  private epoch = 0;
  private actionQueue: Promise<void> = Promise.resolve();
  private paused = false;
  private pendingTyped: string[] = [];
  private typedAwaitingResponse = false;
  private unsubscribers: Array<() => void> = [];
  private feedbackPrompt = true;
  private feedbackAsked = false;
  private feedbackPhase: RealtimeFeedbackPhase = 'idle';
  private connectedAt = 0;
  private expiresAt = 0;
  constructor(private cb: RealtimeCallbacks, private adapter: Adapter, private rate?: RateSession) { this.audio.autoplay = true; }

  private send(event: Record<string, unknown>) {
    if (this.channel?.readyState === 'open') this.channel.send(JSON.stringify(event));
  }
  private system(text: string) {
    this.send({ type: 'conversation.item.create', event_id: crypto.randomUUID(), item: { type: 'message', role: 'system', content: [{ type: 'input_text', text }] } });
  }
  private respond() { this.send({ type: 'response.create', event_id: crypto.randomUUID() }); }
  private elapsedSeconds() { return this.connectedAt ? Math.round((Date.now() - this.connectedAt) / 1000) : 0; }
  private offsetMs() { return this.connectedAt ? Date.now() - this.connectedAt : 0; }
  private async closeOnServer(id = this.requestId, usageSeconds?: number) {
    if (!id) return;
    try {
      const body = usageSeconds === undefined ? {} : { usage_seconds: usageSeconds };
      const result = await voicePost(`sessions/${id}/close`, body, { keepalive: true, token: getAuthToken() ?? this.authToken });
      if (!result.closed) this.cb.task('Voice stopped locally. Server cleanup is pending; its retry watchdog remains active.');
    } catch { this.cb.task('Voice stopped locally. Server cleanup could not be confirmed; the heartbeat lease will expire.'); }
  }
  private cleanup() {
    this.ready = false;
    this.unsubscribers.forEach(unsubscribe => unsubscribe()); this.unsubscribers = []; clearTimeout(this.contextTimer);
    clearInterval(this.heartbeatTimer); clearTimeout(this.startTimer); clearTimeout(this.limitTimer); clearTimeout(this.disconnectedTimer); clearTimeout(this.feedbackTimer);
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
    this.feedbackAsked = false; this.connectedAt = 0; this.expiresAt = 0; this.setFeedbackPhase('idle');
    this.actionQueue = Promise.resolve(); this.epoch++;
    this.seen.clear(); this.calls.clear(); this.batches.clear(); this.transcribed.clear();
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
      channel.onclose = () => { if (generation === this.generation && this.ready && !this.closing) this.fail('Voice disconnected. Please reconnect.'); };
      await peer.setLocalDescription(await peer.createOffer());
      if (peer.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', check); reject(new Error('The browser could not establish an audio route.')); }, 10000);
        const check = () => { if (peer.iceGatheringState === 'complete') { clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', check); resolve(); } };
        peer.addEventListener('icegatheringstatechange', check); check();
      });
      if (generation !== this.generation) return;
      this.requestId = crypto.randomUUID();
      const requestId = this.requestId;
      const result = await voiceStart({ request_id: requestId, sdp: peer.localDescription?.sdp }, { signal: this.abort.signal });
      if (generation !== this.generation) { void this.closeOnServer(requestId); return; }
      this.heartbeatTimer = setInterval(() => {
        // Always heartbeat with the CURRENT token: SSO app tokens live at most 5 minutes, a call lasts up to 10.
        void voicePost(`sessions/${requestId}/heartbeat`, {}, { token: getAuthToken() ?? this.authToken }).catch(() => {
          if (generation === this.generation && !this.closing) this.fail('Voice authorization or heartbeat was lost. Please reconnect.');
        });
      }, 20000);
      await peer.setRemoteDescription({ type: 'answer', sdp: result.transport.sdp });
      const minutes = Math.max(1, Math.round((Number(result.max_seconds) || 600) / 60));
      this.expiresAt = Number(result.expires_at) * 1000 || 0;
      this.limitTimer = setTimeout(() => { this.cb.task(`The ${minutes}-minute voice session limit was reached. Start again to continue.`); this.end({ skipFeedback: true }); }, Math.max(0, result.expires_at * 1000 - Date.now() - 2000));
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
  /** The Realtime API has no mute event: a disabled track sends silence, so nothing is heard or billed as speech. */
  mute(muted: boolean) { this.microphone?.getAudioTracks().forEach(track => { track.enabled = !muted; }); }
  pauseActions(paused: boolean) {
    this.paused = paused; this.epoch++;
    this.cb.task(paused ? 'App actions paused. Submitted analytics queries may still run.' : 'App actions enabled. Ask again for any cancelled request.');
    if (this.ready) this.system(paused ? 'The user paused app actions. Pending actions have been blocked; completed changes remain. Do not claim they were undone. You can still discuss data.' : 'The user re-enabled app actions. Do not replay cancelled work; wait for their next request.');
  }
  typeMessage(text: string) {
    if (!this.ready || this.closing || !text.trim()) return;
    this.pendingTyped.push(text.trim().slice(0, 2000)); this.flushTyped();
  }
  private flushTyped() {
    if (this.closing || this.typedAwaitingResponse || [...this.batches.values()].some(batch => !batch.processed)) return;
    const text = this.pendingTyped.shift(); if (!text) return;
    this.epoch++; this.typedAwaitingResponse = true;
    this.send({ type: 'conversation.item.create', event_id: crypto.randomUUID(), item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } });
    this.respond();
  }
  setFeedbackPrompt(enabled: boolean) { this.feedbackPrompt = enabled; }
  private setFeedbackPhase(phase: RealtimeFeedbackPhase) {
    if (this.feedbackPhase === phase) return;
    this.feedbackPhase = phase; this.cb.feedback?.(phase);
  }
  private shouldAskFeedback() {
    const now = Date.now();
    return !!this.rate && this.feedbackPrompt && !this.feedbackAsked && this.ready && this.channel?.readyState === 'open' && !!this.requestId
      && this.connectedAt > 0 && now - this.connectedAt >= FEEDBACK_MIN_CALL_MS
      && this.expiresAt > 0 && this.expiresAt - now >= FEEDBACK_MIN_LEFT_MS;
  }
  private askFeedback() {
    this.feedbackAsked = true; this.epoch++;
    this.setFeedbackPhase('asking');
    this.cb.task('Asking for quick feedback. Answer the guide, use the rating card, or press End again to finish now.');
    this.system(FEEDBACK_INSTRUCTION); this.respond();
    const wait = Math.min(FEEDBACK_WINDOW_MS, Math.max(0, this.expiresAt - Date.now() - 5000));
    this.feedbackTimer = setTimeout(() => this.end({ skipFeedback: true }), wait);
  }
  async rateSession(rating: unknown, improvement: unknown, endAfter = false): Promise<{ ok: boolean; error?: string; effect?: string }> {
    const id = this.requestId;
    try {
      if (!id || !this.rate) throw new Error('No voice session to rate.');
      if (!Number.isInteger(rating) || Number(rating) < 1 || Number(rating) > 5) throw new Error('The rating must be a whole number from 1 to 5.');
      const text = typeof improvement === 'string' ? improvement.trim().slice(0, 2000) : '';
      await this.rate(id, Number(rating), text);
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : 'Feedback could not be saved.' };
    }
    if (this.feedbackPhase === 'asking') {
      this.setFeedbackPhase('saved');
      clearTimeout(this.feedbackTimer);
      this.feedbackTimer = setTimeout(() => this.end({ skipFeedback: true }), endAfter ? 0 : FEEDBACK_GOODBYE_MS);
    } else this.setFeedbackPhase('saved');
    return { ok: true, effect: 'Feedback saved. Thank you.' };
  }
  /** Realtime has no session.close round trip: report our own call duration and let the server hang up. */
  end(options: { skipFeedback?: boolean } = {}) {
    if (this.closing) return;
    if (!options.skipFeedback && this.shouldAskFeedback()) { this.askFeedback(); return; }
    clearTimeout(this.feedbackTimer);
    this.closing = true; this.epoch++;
    this.cb.status('closing', 'Ending conversation…');
    const seconds = this.ready ? this.elapsedSeconds() : undefined;
    if (seconds !== undefined) this.cb.usage(seconds, true);
    this.generation++; void this.closeOnServer(this.requestId, seconds); this.cleanup(); this.closing = false;
    this.cb.status('idle', 'Conversation ended.');
  }
  dispose() { this.generation++; this.epoch++; this.closing = true; void this.closeOnServer(); this.cleanup(); }
  contextChanged() {
    if (!this.ready || this.closing) return;
    if (!isVoiceDispatch()) this.epoch++;
    clearTimeout(this.contextTimer);
    this.contextTimer = setTimeout(() => {
      if (this.ready && !this.closing) this.system('Application state changed. Call read_app for fresh selected chat, filters and query status before answering state-dependent questions. Prior state may be stale.');
    }, 250);
  }
  private watchApp() { this.unsubscribers = [this.adapter.subscribe(() => this.contextChanged())]; }
  private caption(speaker: Caption['speaker'], delta: string, id?: string) {
    if (!delta) return;
    const at = this.offsetMs();
    this.cb.caption({ id: id || crypto.randomUUID(), speaker, delta, start: at, end: at });
  }
  private batchFor(responseId: string) {
    let batch = this.batches.get(responseId);
    if (!batch) { batch = { calls: [], epoch: this.epoch, processed: false }; this.batches.set(responseId, batch); }
    return batch;
  }
  private onEvent(event: RealtimeEvent) {
    const id = typeof event.event_id === 'string' ? event.event_id : undefined;
    if (id && this.seen.has(id)) return;
    if (id) { this.seen.add(id); if (this.seen.size > 15000) this.seen.delete(this.seen.values().next().value!); }
    if (event.type === 'session.created') {
      if (this.closing || this.ready) return;
      this.ready = true; this.connectedAt = Date.now(); this.watchApp(); clearTimeout(this.startTimer); this.cb.status('connected', 'Listening · you can interrupt naturally');
      this.system(GREETING_INSTRUCTION); this.respond();
    } else if (event.type === 'conversation.item.input_audio_transcription.delta') {
      this.transcribed.add(String(event.item_id ?? '')); this.caption('user', String(event.delta ?? ''), id);
    } else if (event.type === 'conversation.item.input_audio_transcription.completed') {
      // Models without streaming deltas only send the final transcript.
      if (!this.transcribed.has(String(event.item_id ?? ''))) this.caption('user', String(event.transcript ?? ''), id);
    } else if (event.type === 'response.output_audio_transcript.delta' || event.type === 'response.output_text.delta') {
      this.caption('assistant', String(event.delta ?? ''), id);
    } else if (event.type === 'error') {
      const error = event.error as { message?: string; code?: string } | undefined;
      if (!this.ready) this.fail('The voice service could not start. Please check its configuration.');
      else if (error?.code !== 'conversation_already_has_active_response') this.cb.task(`Voice service: ${error?.message || error?.code || 'A command was rejected.'}`);
    } else if (event.type === 'response.created' && !this.closing) {
      this.typedAwaitingResponse = false;
      const response = event.response as { id?: string } | undefined;
      if (response?.id) this.batchFor(response.id);
    } else if (event.type === 'response.output_item.done' && !this.closing) {
      const item = event.item as FunctionCall & { type: string };
      const batch = this.batchFor(String(event.response_id ?? ''));
      if (item?.type === 'function_call' && !batch.calls.some(call => call.call_id === item.call_id)) batch.calls.push(item);
    } else if (event.type === 'response.done' && !this.closing) {
      const response = (event.response ?? {}) as { id?: string; status?: string; output?: Array<FunctionCall & { type: string }> };
      const responseId = String(response.id ?? '');
      const batch = this.batchFor(responseId);
      for (const item of response.output ?? []) if (item.type === 'function_call' && !batch.calls.some(call => call.call_id === item.call_id)) batch.calls.push(item);
      this.cb.usage(this.elapsedSeconds(), false);
      if (response.status !== 'completed') {
        // Interrupted (barge-in) or failed: never run its actions; close the call items so the conversation stays valid.
        batch.processed = true;
        for (const call of batch.calls) this.send({ type: 'conversation.item.create', event_id: crypto.randomUUID(), item: { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify({ ok: false, cancelled: true, error: 'Interrupted before it ran. Follow only the newest request.' }) } });
        if (response.status === 'failed') this.cb.task('The guide could not finish that answer. Please ask again.');
        this.flushTyped(); return;
      }
      this.process(batch);
    }
  }
  private process(batch: Batch) {
    const generation = this.generation;
    this.actionQueue = this.actionQueue.then(async () => {
      if (generation !== this.generation || this.closing || batch.processed) return;
      batch.processed = true;
      for (const call of batch.calls) {
        if (generation !== this.generation || this.closing) return;
        let result = this.calls.get(call.call_id);
        if (!result) {
          const stale = batch.epoch !== this.epoch;
          // Rating the call changes nothing in the app, so Pause actions does not block it.
          const read = EFFECTS[call.name] === 'read' || call.name === FEEDBACK_TOOL;
          if (stale || (this.paused && !read)) result = { ok: false, cancelled: true, error: 'This action was cancelled or superseded. Read current state and follow only the newest request. Do not replay it.' };
          else {
            this.cb.task(`${call.name.replace(/_/g, ' ')}…`);
            try {
              if (call.name === FEEDBACK_TOOL) {
                const args = JSON.parse(call.arguments) as Record<string, unknown>;
                result = await this.rateSession(args.rating, args.improvement);
              } else result = await this.adapter.execute(call.name, JSON.parse(call.arguments), this.abort!.signal, () => generation === this.generation && !this.closing && batch.epoch === this.epoch && (!this.paused || read));
            } catch { result = { ok: false, error: 'Invalid tool arguments' }; }
          }
          this.calls.set(call.call_id, result);
        }
        if (generation !== this.generation || this.closing) return;
        this.send({ type: 'conversation.item.create', event_id: crypto.randomUUID(), item: { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result) } });
        this.cb.task(result.ok ? String(result.effect || 'Information retrieved.') : String(result.error));
        if (result.excerpts || result.messages || result.reporting_phases) this.cb.evidence(result);
      }
      if (batch.calls.length) this.respond();
      else { this.cb.task('Ready for your next question.'); this.flushTyped(); }
      if (this.batches.size > 250) for (const [key, old] of this.batches) { if (old.processed && old !== batch) { this.batches.delete(key); if (this.batches.size <= 200) break; } }
    }).catch(() => this.cb.task('Could not complete an app action. Please retry.'));
  }
}

export type { Caption, VoiceStatus };
