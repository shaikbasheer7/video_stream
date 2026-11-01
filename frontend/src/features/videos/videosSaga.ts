import type { PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { call, put, takeEvery, takeLatest } from 'redux-saga/effects';
import { api, errorMessage } from '../../app/api';
import type { Paginated, Video } from '../../types/api';
import {
  browseLoaded,
  browseRequested,
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
} from './videosSlice';

function* fetchBrowse() {
  try {
    const { data }: { data: Paginated<Video> } = yield call(api.get, '/videos/');
    yield put(browseLoaded(data.results));
  } catch (error) {
    yield put(videosFailed(errorMessage(error)));
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
    yield put(myVideosLoaded(data.results));
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
  yield takeLatest(feedRequested.type, fetchFeed);
  yield takeLatest(followRequested.type, changeFollow);
  yield takeLatest(myVideosRequested.type, fetchMyVideos);
  yield takeLatest(videoRequested.type, fetchVideo);
  yield takeEvery(videoDeleteRequested.type, deleteVideo);
}
