import { runSaga, stdChannel, type Saga } from 'redux-saga';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../app/api';
import * as events from './eventsSaga';
import type { PlaybackEvent } from './tracker';

const sample = (i: number): PlaybackEvent => ({
  type: 'progress',
  video_id: 'vid-1',
  session_id: 's',
  ts: new Date(0).toISOString(),
  position_sec: i,
  quality: '720p',
});

function start() {
  vi.useFakeTimers();
  const actions = stdChannel();
  const task = runSaga(
    { channel: actions, dispatch: (a) => actions.put(a), getState: () => ({ auth: { accessToken: 'tok' } }) },
    events.default as Saga,
  );
  const dispatch = (n: number, from = 0) => {
    for (let i = from; i < from + n; i++) actions.put(events.playbackEvent(sample(i)));
  };
  return { task, dispatch };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('eventsSaga', () => {
  it('flushes as soon as 50 events are buffered', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const { task, dispatch } = start();
    dispatch(49);
    await vi.advanceTimersByTimeAsync(0);
    expect(post).not.toHaveBeenCalled();
    dispatch(1, 49);
    await vi.advanceTimersByTimeAsync(0);
    expect(post).toHaveBeenCalledTimes(1);
    const body = post.mock.calls[0][1] as { anonymous_id: string; events: PlaybackEvent[] };
    expect(body.events.map((e) => e.position_sec)).toEqual(Array.from({ length: 50 }, (_, i) => i));
    expect(body.anonymous_id).toBeTruthy();
    task.cancel();
  });

  it('flushes every 15 s even while events keep arriving', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const { task, dispatch } = start();
    for (let s = 0; s < 16; s += 2) {
      dispatch(1, s);
      await vi.advanceTimersByTimeAsync(2000); // a steady trickle must not postpone the flush forever
    }
    expect(post).toHaveBeenCalledTimes(1);
    task.cancel();
  });

  it('keeps events when the API is down and sends them with the next flush', async () => {
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('503')).mockResolvedValue({ data: {} });
    const { task, dispatch } = start();
    dispatch(3);
    await vi.advanceTimersByTimeAsync(15_000);
    dispatch(1, 3);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(post).toHaveBeenCalledTimes(2);
    expect((post.mock.calls[1][1] as { events: PlaybackEvent[] }).events).toHaveLength(4);
    task.cancel();
  });

  it('sends whatever is buffered with keepalive fetch when the page is hidden', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const { task, dispatch } = start();
    dispatch(5);
    await vi.advanceTimersByTimeAsync(0);
    window.dispatchEvent(new Event('pagehide')); // tab closed / navigated away
    await vi.advanceTimersByTimeAsync(0);

    expect(post).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/events/batch/?final=1');
    expect(init.keepalive).toBe(true);
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body as string).events).toHaveLength(5);
    task.cancel();
    vi.unstubAllGlobals();
  });
});
