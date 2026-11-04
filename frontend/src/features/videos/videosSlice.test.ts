import { describe, expect, it } from 'vitest';
import type { Video } from '../../types/api';
import reducer, {
  browseLoaded,
  browseMoreLoaded,
  browseMoreRequested,
  liveLoaded,
  myVideosLoaded,
  myVideosMoreLoaded,
  searchFailed,
  searchLoaded,
  searchRequested,
  similarLoaded,
  similarRequested,
  videoDeleted,
  videoLoaded,
  videoRequested,
  videoViewersLoaded,
  videoViewersRequested,
} from './videosSlice';

const video = (id: string, resume: number | null | undefined) => ({ id, resume_position_sec: resume }) as Video;

describe('videosSlice live numbers', () => {
  it("never shows one video's viewer count on another", () => {
    let state = reducer(undefined, videoViewersLoaded({ videoId: 'a', viewers: 4 }));
    state = reducer(state, videoViewersRequested('a'));
    expect(state.videoViewers?.viewers).toBe(4);
    state = reducer(state, videoViewersRequested('b'));
    expect(state.videoViewers).toBeNull();
  });

  it('goes back to showing nothing when the stream stops', () => {
    let state = reducer(undefined, liveLoaded({ viewersNow: 3, trending: [] }));
    expect(state.live?.viewersNow).toBe(3);
    state = reducer(state, liveLoaded(null));
    expect(state.live).toBeNull();
  });
});

describe('videosSlice pagination', () => {
  const dated = (id: string, created_at: string) => ({ id, created_at }) as Video;

  it('adds the next page without repeating a video that shifted onto it', () => {
    let state = reducer(undefined, browseLoaded({ results: [dated('a', '3'), dated('b', '2')], hasMore: true }));
    state = reducer(state, browseMoreRequested());
    expect(state.loadingMore).toBe(true);
    state = reducer(state, browseMoreLoaded({ results: [dated('b', '2'), dated('c', '1')], hasMore: false }));
    expect(state.browse.map((v) => v.id)).toEqual(['a', 'b', 'c']);
    expect(state).toMatchObject({ browsePage: 2, browseHasMore: false, loadingMore: false });
  });

  it('keeps older pages when the library refreshes page 1, and adds a new upload on top', () => {
    let state = reducer(undefined, myVideosLoaded({ results: [dated('b', '3')], hasMore: true }));
    state = reducer(state, myVideosMoreLoaded({ results: [dated('a', '2')], hasMore: true }));
    state = reducer(state, myVideosLoaded({ results: [dated('new', '4'), dated('b', '3')], hasMore: true }));
    expect(state.mine.map((v) => v.id)).toEqual(['new', 'b', 'a']);
    expect(state).toMatchObject({ minePage: 2, mineHasMore: true });
  });
});

describe('videosSlice search', () => {
  const loaded = () => reducer(reducer(undefined, searchRequested('cats')), searchLoaded([video('a', null)]));

  it('keeps results while the same words are searched again, and clears them for new words', () => {
    expect(reducer(loaded(), searchRequested('cats')).search.results).toHaveLength(1);
    expect(reducer(loaded(), searchRequested('dogs')).search.results).toEqual([]);
  });

  it('reports a failure without leaving old results or a spinner', () => {
    const { search } = reducer(loaded(), searchFailed('Network error'));
    expect(search).toMatchObject({ results: [], loading: false, error: 'Network error' });
  });

  it('drops a deleted video from the results', () => {
    expect(reducer(loaded(), videoDeleted('a')).search.results).toEqual([]);
  });
});

describe('videosSlice similar videos', () => {
  it("never keeps showing the previous video's list while the next one loads", () => {
    const loaded = { videoId: 'a', source: 'similar' as const, items: [video('b', null)] };
    let state = reducer(undefined, similarLoaded(loaded));
    state = reducer(state, similarRequested('a')); // same video: keep it on screen
    expect(state.similar).toEqual(loaded);
    state = reducer(state, similarRequested('c'));
    expect(state.similar).toBeNull();
  });
});

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
