import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { Video } from '../../types/api';

export type RecommendationSource = 'personalized' | 'trending' | 'latest';

export interface VideoPage {
  results: Video[];
  hasMore: boolean;
}

/** A video can shift to the next page when a newer one arrives, so it may come back twice. */
function addPage(existing: Video[], results: Video[]): Video[] {
  const seen = new Set(existing.map((v) => v.id));
  return [...existing, ...results.filter((v) => !seen.has(v.id))];
}

export interface VideosState {
  browse: Video[];
  browseLoading: boolean;
  browsePage: number;
  browseHasMore: boolean;
  minePage: number;
  mineHasMore: boolean;
  loadingMore: boolean;
  recommended: Video[];
  recommendedSource: RecommendationSource | null;
  trending: Video[];
  similar: { videoId: string; source: 'similar' | 'trending'; items: Video[] } | null;
  feed: Video[];
  feedLoading: boolean;
  mine: Video[];
  loading: boolean;
  current: Video | null;
  currentLoading: boolean;
  currentError: string | null;
  error: string | null;
  search: { query: string; results: Video[]; loading: boolean; error: string | null };
}

const initialState: VideosState = {
  browse: [],
  browseLoading: false,
  browsePage: 1,
  browseHasMore: false,
  minePage: 1,
  mineHasMore: false,
  loadingMore: false,
  recommended: [],
  recommendedSource: null,
  trending: [],
  similar: null,
  feed: [],
  feedLoading: false,
  mine: [],
  loading: false,
  current: null,
  currentLoading: false,
  currentError: null,
  error: null,
  search: { query: '', results: [], loading: false, error: null },
};

const videosSlice = createSlice({
  name: 'videos',
  initialState,
  reducers: {
    browseRequested(state) {
      state.browseLoading = true;
      state.error = null;
    },
    browseLoaded(state, action: PayloadAction<VideoPage>) {
      state.browse = action.payload.results;
      state.browsePage = 1;
      state.browseHasMore = action.payload.hasMore;
      state.browseLoading = false;
    },
    browseMoreRequested(state) {
      state.loadingMore = true;
      state.error = null;
    },
    browseMoreLoaded(state, action: PayloadAction<VideoPage>) {
      state.browse = addPage(state.browse, action.payload.results);
      state.browsePage += 1;
      state.browseHasMore = action.payload.hasMore;
      state.loadingMore = false;
    },
    recommendationsRequested() {},
    recommendationsLoaded(
      state,
      action: PayloadAction<{ source: RecommendationSource; recommended: Video[]; trending: Video[] }>,
    ) {
      state.recommendedSource = action.payload.source;
      state.recommended = action.payload.recommended;
      state.trending = action.payload.trending;
    },
    similarRequested(state, action: PayloadAction<string>) {
      if (state.similar?.videoId !== action.payload) state.similar = null;
    },
    similarLoaded(state, action: PayloadAction<VideosState['similar']>) {
      state.similar = action.payload;
    },
    searchRequested(state, action: PayloadAction<string>) {
      // Never shows the results of the previous words under the new ones.
      const results = state.search.query === action.payload ? state.search.results : [];
      state.search = { query: action.payload, results, loading: true, error: null };
    },
    searchLoaded(state, action: PayloadAction<Video[]>) {
      state.search.results = action.payload;
      state.search.loading = false;
    },
    searchFailed(state, action: PayloadAction<string>) {
      state.search.results = [];
      state.search.loading = false;
      state.search.error = action.payload;
    },
    feedRequested(state) {
      state.feedLoading = true;
      state.error = null;
    },
    feedLoaded(state, action: PayloadAction<Video[]>) {
      state.feed = action.payload;
      state.feedLoading = false;
    },
    followRequested(_state, _action: PayloadAction<{ userId: number; follow: boolean }>) {},
    followChanged(state, action: PayloadAction<{ userId: number; following: boolean }>) {
      if (state.current?.owner_id === action.payload.userId) state.current.is_following = action.payload.following;
    },
    myVideosRequested(state) {
      state.loading = true;
      state.error = null;
    },
    myVideosLoaded(state, action: PayloadAction<VideoPage>) {
      const { results, hasMore } = action.payload;
      state.loading = false;
      if (state.minePage > 1 && results.length > 0) {
        // The library refreshes page 1 while something encodes: keep the older pages already on screen.
        const ids = new Set(results.map((v) => v.id));
        const oldest = results[results.length - 1].created_at;
        state.mine = [...results, ...state.mine.filter((v) => !ids.has(v.id) && v.created_at < oldest)];
        return;
      }
      state.mine = results;
      state.minePage = 1;
      state.mineHasMore = hasMore;
    },
    myVideosMoreRequested(state) {
      state.loadingMore = true;
      state.error = null;
    },
    myVideosMoreLoaded(state, action: PayloadAction<VideoPage>) {
      state.mine = addPage(state.mine, action.payload.results);
      state.minePage += 1;
      state.mineHasMore = action.payload.hasMore;
      state.loadingMore = false;
    },
    videosFailed(state, action: PayloadAction<string>) {
      state.loading = false;
      state.browseLoading = false;
      state.feedLoading = false;
      state.loadingMore = false;
      state.error = action.payload;
    },
    // Also used to renew the CDN cookies: fetching details sets fresh ones.
    videoRequested(state, action: PayloadAction<string>) {
      if (state.current?.id !== action.payload) state.current = null;
      state.currentLoading = true;
      state.currentError = null;
    },
    videoLoaded(state, action: PayloadAction<Video>) {
      const previous = state.current;
      const video = action.payload;
      // A re-fetch of the same video (e.g. to renew CDN cookies) reports a newer watch position;
      // keep the original one so the player isn't restarted mid-playback.
      if (previous?.id === video.id && previous.resume_position_sec !== undefined) {
        video.resume_position_sec = previous.resume_position_sec;
      }
      state.current = video;
      state.currentLoading = false;
    },
    videoLoadFailed(state, action: PayloadAction<string>) {
      state.currentLoading = false;
      state.currentError = action.payload;
    },
    videoDeleteRequested(_state, _action: PayloadAction<string>) {},
    videoDeleted(state, action: PayloadAction<string>) {
      state.mine = state.mine.filter((v) => v.id !== action.payload);
      state.browse = state.browse.filter((v) => v.id !== action.payload);
      state.search.results = state.search.results.filter((v) => v.id !== action.payload);
    },
  },
});

export const {
  browseRequested,
  browseLoaded,
  browseMoreRequested,
  browseMoreLoaded,
  recommendationsRequested,
  recommendationsLoaded,
  similarRequested,
  similarLoaded,
  searchRequested,
  searchLoaded,
  searchFailed,
  feedRequested,
  feedLoaded,
  followRequested,
  followChanged,
  myVideosRequested,
  myVideosLoaded,
  myVideosMoreRequested,
  myVideosMoreLoaded,
  videosFailed,
  videoRequested,
  videoLoaded,
  videoLoadFailed,
  videoDeleteRequested,
  videoDeleted,
} = videosSlice.actions;

export default videosSlice.reducer;
