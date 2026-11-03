import type { PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { all, call, put, select, takeEvery, takeLatest, takeLeading } from 'redux-saga/effects';
import { api, errorMessage } from '../../app/api';
import type { Paginated, Video } from '../../types/api';
import {
  browseLoaded,
  browseMoreLoaded,
  browseMoreRequested,
  browseRequested,
  myVideosMoreLoaded,
  myVideosMoreRequested,
  recommendationsLoaded,
  recommendationsRequested,
  similarLoaded,
  similarRequested,
  searchFailed,
  searchLoaded,
  searchRequested,
  type RecommendationSource,
  feedLoaded,
  feedRequested,
  followChanged,
  followRequested,
  myVideosLoaded,
  myVideosRequested,
  videoDeleted,
  videoDeleteRequested,
  videoLoaded,
  videoLoadFailed,
  videoRequested,
  videosFailed,
  type VideosState,
} from './videosSlice';

const toPage = (data: Paginated<Video>) => ({ results: data.results, hasMore: data.next !== null });

function* fetchBrowse() {
  try {
    const { data }: { data: Paginated<Video> } = yield call(api.get, '/videos/');
    yield put(browseLoaded(toPage(data)));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

function* fetchMoreBrowse() {
  try {
    const page: number = yield select((s: { videos: VideosState }) => s.videos.browsePage);
    const { data }: { data: Paginated<Video> } = yield call(api.get, '/videos/', { params: { page: page + 1 } });
    yield put(browseMoreLoaded(toPage(data)));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

// These sections are extras on top of the catalogue: if they fail, the page simply goes without them.
function* fetchRecommendations() {
  try {
    const [personal, trending]: [
      { data: { source: RecommendationSource; results: Video[] } },
      { data: { results: Video[] } },
    ] = yield all([call(api.get, '/recommendations/'), call(api.get, '/recommendations/trending/')]);
    yield put(
      recommendationsLoaded({
        source: personal.data.source,
        recommended: personal.data.results,
        trending: trending.data.results,
      }),
    );
  } catch {
    yield put(recommendationsLoaded({ source: 'latest', recommended: [], trending: [] }));
  }
}

function* fetchSimilar(action: PayloadAction<string>) {
  const videoId = action.payload;
  try {
    const { data }: { data: { source: 'similar' | 'trending'; results: Video[] } } = yield call(
      api.get,
      `/videos/${videoId}/similar/`,
      { params: { limit: 8 } },
    );
    yield put(similarLoaded({ videoId, source: data.source, items: data.results }));
  } catch {
    yield put(similarLoaded(null));
  }
}

function* fetchSearch(action: PayloadAction<string>) {
  try {
    const { data }: { data: { results: Video[] } } = yield call(api.get, '/search/', { params: { q: action.payload } });
    yield put(searchLoaded(data.results));
  } catch (error) {
    yield put(searchFailed(errorMessage(error)));
  }
}

function* fetchFeed() {
  try {
    const { data }: { data: { results: Video[] } } = yield call(api.get, '/feed/');
    yield put(feedLoaded(data.results));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

function* changeFollow(action: PayloadAction<{ userId: number; follow: boolean }>) {
  const { userId, follow } = action.payload;
  try {
    const url = `/users/${userId}/follow/`;
    const { data }: { data: { following: boolean } } = yield call(follow ? api.post : api.delete, url);
    yield put(followChanged({ userId, following: data.following }));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

function* fetchMyVideos() {
  try {
    const { data }: { data: Paginated<Video> } = yield call(api.get, '/videos/', { params: { mine: true } });
    yield put(myVideosLoaded(toPage(data)));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

function* fetchMoreMyVideos() {
  try {
    const page: number = yield select((s: { videos: VideosState }) => s.videos.minePage);
    const { data }: { data: Paginated<Video> } = yield call(api.get, '/videos/', {
      params: { mine: true, page: page + 1 },
    });
    yield put(myVideosMoreLoaded(toPage(data)));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

function* fetchVideo(action: PayloadAction<string>) {
  try {
    const { data }: { data: Video } = yield call(api.get, `/videos/${action.payload}/`);
    yield put(videoLoaded(data));
  } catch (error) {
    const notFound = axios.isAxiosError(error) && error.response?.status === 404;
    yield put(videoLoadFailed(notFound ? 'This video does not exist or is not available yet.' : errorMessage(error)));
  }
}

function* deleteVideo(action: PayloadAction<string>) {
  try {
    yield call(api.delete, `/videos/${action.payload}/`);
    yield put(videoDeleted(action.payload));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
  }
}

export default function* videosSaga() {
  yield takeLatest(browseRequested.type, fetchBrowse);
  yield takeLeading(browseMoreRequested.type, fetchMoreBrowse);
  yield takeLeading(myVideosMoreRequested.type, fetchMoreMyVideos);
  yield takeLatest(recommendationsRequested.type, fetchRecommendations);
  yield takeLatest(similarRequested.type, fetchSimilar);
  yield takeLatest(searchRequested.type, fetchSearch);
  yield takeLatest(feedRequested.type, fetchFeed);
  yield takeLatest(followRequested.type, changeFollow);
  yield takeLatest(myVideosRequested.type, fetchMyVideos);
  yield takeLatest(videoRequested.type, fetchVideo);
  yield takeEvery(videoDeleteRequested.type, deleteVideo);
}
