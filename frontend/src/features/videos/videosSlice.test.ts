import { describe, expect, it } from 'vitest';
import type { Video } from '../../types/api';
import reducer, { videoLoaded, videoRequested } from './videosSlice';

const video = (id: string, resume: number | null | undefined) => ({ id, resume_position_sec: resume }) as Video;

describe('videosSlice resume position', () => {
  it('keeps the first resume position when the same video is re-fetched (cookie renewal)', () => {
    let state = reducer(undefined, videoLoaded(video('a', 42)));
    state = reducer(state, videoRequested('a'));
    state = reducer(state, videoLoaded(video('a', 95))); // the viewer has watched on since
    expect(state.current?.resume_position_sec).toBe(42);
  });

  it('uses the new position for a different video, or once the first load had none', () => {
    let state = reducer(undefined, videoLoaded(video('a', 42)));
    state = reducer(state, videoLoaded(video('b', 10)));
    expect(state.current?.resume_position_sec).toBe(10);

    state = reducer(undefined, videoLoaded(video('c', undefined))); // anonymous load
    state = reducer(state, videoLoaded(video('c', 30))); // logged in on the page
    expect(state.current?.resume_position_sec).toBe(30);
  });
});
