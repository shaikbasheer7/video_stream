// Turns <video>/hls.js callbacks into the playback events of blueprint section 12.1.
// Framework-free so it can be unit-tested; HlsPlayer wires it up.

export type PlaybackEventType = 'play' | 'pause' | 'seek' | 'progress' | 'quality_change' | 'buffering' | 'complete';

export interface PlaybackEvent {
  type: PlaybackEventType;
  video_id: string;
  session_id: string;
  ts: string;
  position_sec: number;
  quality: string | null;
  from_sec?: number;
  to_sec?: number;
  from_quality?: string;
  to_quality?: string;
  auto?: boolean;
  duration_ms?: number;
  watch_time_sec?: number;
}

export const PROGRESS_EVERY_SEC = 10;
const COMPLETE_AT = 0.95;
const MAX_TICK_SEC = 1.5; // larger jumps between timeupdates are seeks, not watching

function newSessionId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export class PlaybackTracker {
  readonly sessionId = newSessionId();
  quality: string | null = null;
  private lastPosition = 0;
  private lastProgressAt = 0;
  private watchTime = 0;
  private completed = false;
  private seeking = false;
  private bufferingSince: number | null = null;

  constructor(
    private readonly videoId: string,
    private readonly emit: (event: PlaybackEvent) => void,
    private readonly now: () => number = Date.now,
  ) {}

  private send(type: PlaybackEventType, position: number, extra: Partial<PlaybackEvent> = {}) {
    this.emit({
      type,
      video_id: this.videoId,
      session_id: this.sessionId,
      ts: new Date(this.now()).toISOString(),
      position_sec: Math.round(position * 10) / 10,
      quality: this.quality,
      ...extra,
    });
  }

  onPlay(position: number) {
    this.lastPosition = position;
    this.lastProgressAt = position;
    this.send('play', position);
  }

  onPause(position: number, ended: boolean) {
    if (!ended) this.send('pause', position);
  }

  onSeeking() {
    this.seeking = true;
  }

  onSeeked(position: number) {
    this.seeking = false;
    this.send('seek', position, { from_sec: Math.round(this.lastPosition * 10) / 10, to_sec: Math.round(position * 10) / 10 });
    this.lastPosition = position;
    this.lastProgressAt = position;
  }

  onTimeUpdate(position: number, duration: number, paused: boolean) {
    // Browsers fire timeupdate mid-seek; the jump isn't watching.
    if (this.seeking) return;
    const delta = position - this.lastPosition;
    if (!paused && delta > 0 && delta <= MAX_TICK_SEC) this.watchTime += delta;
    this.lastPosition = position;

    if (!paused && position - this.lastProgressAt >= PROGRESS_EVERY_SEC) {
      this.lastProgressAt = position;
      this.send('progress', position);
    }
    if (!this.completed && duration > 0 && position >= duration * COMPLETE_AT) {
      this.completed = true;
      this.send('complete', position, { watch_time_sec: Math.round(this.watchTime * 10) / 10 });
    }
  }

  onWaiting() {
    if (this.bufferingSince === null && !this.seeking) this.bufferingSince = this.now();
  }

  onPlaying(position: number) {
    if (this.bufferingSince !== null) {
      this.send('buffering', position, { duration_ms: this.now() - this.bufferingSince });
      this.bufferingSince = null;
    }
  }

  onQualityChange(to: string, auto: boolean, position: number) {
    const from = this.quality;
    this.quality = to;
    if (from && from !== to) this.send('quality_change', position, { from_quality: from, to_quality: to, auto });
  }
}
