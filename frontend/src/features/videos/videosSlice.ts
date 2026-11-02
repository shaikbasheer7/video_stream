import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { Video } from '../../types/api';

export type RecommendationSource = 'personalized' | 'trending' | 'latest';

export interface VideosState {
  browse: Video[];
  browseLoading: boolean;
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
}

const initialState: VideosState = {
  browse: [],
  browseLoading: false,
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
};

const videosSlice = createSlice({
  name: 'videos',
  initialState,
  reducers: {
    browseRequested(state) {
      state.browseLoading = true;
      state.error = null;
    },
    browseLoaded(state, action: PayloadAction<Video[]>) {
      state.browse = action.payload;
      state.browseLoading = false;
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
    myVideosLoaded(state, action: PayloadAction<Video[]>) {
      state.mine = action.payload;
      state.loading = false;
    },
    videosFailed(state, action: PayloadAction<string>) {
      state.loading = false;
      state.browseLoading = false;
      state.feedLoading = false;
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
    },
  },
});

export const {
  browseRequested,
  browseLoaded,
  recommendationsRequested,
  recommendationsLoaded,
  similarRequested,
  similarLoaded,
  feedRequested,
  feedLoaded,
  followRequested,
  followChanged,
  myVideosRequested,
  myVideosLoaded,
  videosFailed,
  videoRequested,
  videoLoaded,
  videoLoadFailed,
  videoDeleteRequested,
  videoDeleted,
} = videosSlice.actions;

export default videosSlice.reducer;
