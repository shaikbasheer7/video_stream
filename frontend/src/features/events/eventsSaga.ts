import { createAction } from '@reduxjs/toolkit';
import { buffers, END, eventChannel, type Channel, type EventChannel } from 'redux-saga';
import { actionChannel, call, delay, race, select, take } from 'redux-saga/effects';
import { api } from '../../app/api';
import type { PlaybackEvent } from './tracker';

export const playbackEvent = createAction<PlaybackEvent>('events/playback');

export const FLUSH_INTERVAL_MS = 15_000;
export const BATCH_SIZE = 50;
const MAX_BUFFERED = 500; // if the API is down for a long time, drop the oldest
const ENDPOINT = '/events/batch/';

let memoryAnonymousId: string | null = null;

/** Stable per browser so logged-out viewing still links up across sessions. */
export function anonymousId(): string {
  const key = 'streamline.anonymous_id';
  try {
    const stored = localStorage.getItem(key);
    if (stored) return stored;
    const id = crypto.randomUUID();
    localStorage.setItem(key, id);
    return id;
  } catch {
    memoryAnonymousId ??= `mem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    return memoryAnonymousId;
  }
}

/** Emits once whenever the page is hidden or unloaded: the last moment we can send data. */
export function pageHiddenChannel(): EventChannel<true> {
  return eventChannel<true>((emit) => {
    const onVisibility = () => document.visibilityState === 'hidden' && emit(true);
    const onPageHide = () => emit(true);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
    };
  });
}

/**
 * Final flush while the page goes away. keepalive fetch (unlike sendBeacon) can carry the Authorization
 * header, so events stay attributed to the user. ?final=1 lets the server keep them even if the token
 * has just expired. sendBeacon is the fallback where keepalive fetch is unavailable.
 */
export function sendFinal(events: PlaybackEvent[], token: string | null) {
  for (let i = 0; i < events.length; i += BATCH_SIZE) {
    const body = JSON.stringify({ anonymous_id: anonymousId(), events: events.slice(i, i + BATCH_SIZE) });
    const url = `/api${ENDPOINT}?final=1`;
    try {
      void fetch(url, {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body,
      }).catch(() => {});
    } catch {
      navigator.sendBeacon?.(url, new Blob([body], { type: 'application/json' }));
    }
  }
}

function* flush(buffer: PlaybackEvent[]) {
  while (buffer.length) {
    const batch = buffer.splice(0, BATCH_SIZE);
    try {
      // Through `api`: an expired token is refreshed and the request retried.
      yield call(api.post, ENDPOINT, { anonymous_id: anonymousId(), events: batch });
    } catch {
      buffer.unshift(...batch); // keep for the next attempt
      if (buffer.length > MAX_BUFFERED) buffer.splice(0, buffer.length - MAX_BUFFERED);
      return;
    }
  }
}

export default function* eventsSaga() {
  const buffer: PlaybackEvent[] = [];
  // Buffered channel: events dispatched while a flush is in flight aren't lost.
  const events: Channel<ReturnType<typeof playbackEvent>> = yield actionChannel(playbackEvent.type, buffers.expanding(100));
  const hidden: EventChannel<true> = yield call(pageHiddenChannel);
  let lastFlush = Date.now();

  while (true) {
    const wait = Math.max(0, FLUSH_INTERVAL_MS - (Date.now() - lastFlush));
    const result: { event?: ReturnType<typeof playbackEvent>; pageHidden?: true | typeof END } = yield race({
      event: take(events),
      pageHidden: take(hidden),
      tick: delay(wait),
    });

    if (result.event) {
      buffer.push(result.event.payload);
      if (buffer.length < BATCH_SIZE) continue;
    } else if (result.pageHidden) {
      const token: string | null = yield select((s: { auth: { accessToken: string | null } }) => s.auth.accessToken);
      sendFinal(buffer.splice(0), token);
      lastFlush = Date.now();
      continue;
    }
    if (buffer.length) yield call(flush, buffer);
    lastFlush = Date.now();
  }
}
