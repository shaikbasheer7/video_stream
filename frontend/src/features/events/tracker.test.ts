import { describe, expect, it } from 'vitest';
import { PlaybackTracker, type PlaybackEvent } from './tracker';

function setup() {
  const events: PlaybackEvent[] = [];
  let clock = Date.UTC(2026, 10, 1, 10, 0, 0);
  const tracker = new PlaybackTracker('vid-1', (e) => events.push(e), () => clock);
  const advance = (ms: number) => (clock += ms);
  /** Simulates timeupdates every 0.25 s of watching. */
  const watch = (from: number, to: number, duration = 120) => {
    for (let t = from; t <= to + 1e-9; t += 0.25) {
      advance(250);
      tracker.onTimeUpdate(t, duration, false);
    }
  };
  return { tracker, events, advance, watch, types: () => events.map((e) => e.type) };
}

describe('PlaybackTracker', () => {
  it('emits play and a progress event every 10 s of playback', () => {
    const { tracker, events, watch, types } = setup();
    tracker.onQualityChange('720p', true, 0);
    tracker.onPlay(0);
    watch(0, 25);
    expect(types()).toEqual(['play', 'progress', 'progress']);
    expect(events[1]).toMatchObject({ position_sec: 10, quality: '720p', video_id: 'vid-1' });
    expect(new Set(events.map((e) => e.session_id)).size).toBe(1);
  });

  it('records seeks from the last watched position, and restarts the progress clock', () => {
    const { tracker, events, watch, types } = setup();
    tracker.onPlay(0);
    watch(0, 7);
    tracker.onSeeking();
    tracker.onTimeUpdate(60, 120, false); // timeupdate fires during the seek
    tracker.onSeeked(60);
    watch(60, 69);
    expect(types()).toEqual(['play', 'seek']); // no progress: only 9 s since the seek
    expect(events[1]).toMatchObject({ from_sec: 7, to_sec: 60 });
  });

  it('measures buffering stalls and reports quality changes after the first level', () => {
    const { tracker, events, advance } = setup();
    tracker.onQualityChange('1080p', true, 0); // initial level: not a change
    tracker.onWaiting();
    advance(1200);
    tracker.onPlaying(14);
    tracker.onQualityChange('480p', true, 14);
    tracker.onQualityChange('480p', true, 15); // same level again: ignored
    expect(events).toMatchObject([
      { type: 'buffering', duration_ms: 1200, quality: '1080p' },
      { type: 'quality_change', from_quality: '1080p', to_quality: '480p', auto: true, quality: '480p' },
    ]);
  });

  it('records the final position when the viewer leaves, once, and not if paused', () => {
    const { tracker, events, watch, types } = setup();
    tracker.onPlay(0);
    watch(0, 7);
    tracker.onLeaving(7, false);
    tracker.onLeaving(7, false); // visibilitychange and pagehide both fire when a tab closes
    expect(types()).toEqual(['play', 'progress']);
    expect(events[1].position_sec).toBe(7);

    tracker.onPause(9, false);
    tracker.onLeaving(9, true); // the pause event already recorded it
    expect(types()).toEqual(['play', 'progress', 'pause']);
  });

  it('emits complete once at 95% with the time actually watched (seeks excluded)', () => {
    const { tracker, events, watch, types } = setup();
    tracker.onPlay(0);
    watch(0, 20, 100);
    tracker.onSeeking();
    tracker.onSeeked(80);
    watch(80, 99, 100);
    tracker.onPause(100, true); // ended: no pause event
    const complete = events.filter((e) => e.type === 'complete');
    expect(complete).toHaveLength(1);
    expect(complete[0].watch_time_sec).toBeGreaterThan(33);
    expect(complete[0].watch_time_sec).toBeLessThan(36);
    expect(types()).not.toContain('pause');
  });
});
