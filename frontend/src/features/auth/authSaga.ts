import type { PayloadAction } from '@reduxjs/toolkit';
import { call, put, takeLatest } from 'redux-saga/effects';
import { api, errorMessage, refreshAccessToken } from '../../app/api';
import type { Credentials, LoginResponse, RegisterPayload, User } from '../../types/api';
import {
  authFailed,
  loggedOut,
  loginRequested,
  loginSucceeded,
  logoutRequested,
  registerRequested,
  sessionRestoreRequested,
  tokenRefreshed,
} from './authSlice';

function* login(credentials: Credentials) {
  const { data }: { data: LoginResponse } = yield call(api.post, '/auth/login/', credentials);
  yield put(loginSucceeded(data));
}

function* handleLogin(action: PayloadAction<Credentials>) {
  try {
    yield call(login, action.payload);
  } catch (error) {
    yield put(authFailed(errorMessage(error)));
  }
}

function* handleRegister(action: PayloadAction<RegisterPayload>) {
  try {
    yield call(api.post, '/auth/register/', action.payload);
    yield call(login, { email: action.payload.email, password: action.payload.password });
  } catch (error) {
    yield put(authFailed(errorMessage(error)));
  }
}

/** On page load the in-memory access token is gone; the refresh cookie restores the session. */
function* handleSessionRestore() {
  try {
    const access: string = yield call(refreshAccessToken);
    yield put(tokenRefreshed(access));
    const { data }: { data: User } = yield call(api.get, '/auth/me/');
    yield put(loginSucceeded({ access, user: data }));
  } catch {
    yield put(loggedOut());
  }
}

function* handleLogout() {
  try {
    yield call(api.post, '/auth/logout/');
  } finally {
    yield put(loggedOut());
  }
}

export default function* authSaga() {
  yield takeLatest(sessionRestoreRequested.type, handleSessionRestore);
  yield takeLatest(loginRequested.type, handleLogin);
  yield takeLatest(registerRequested.type, handleRegister);
  yield takeLatest(logoutRequested.type, handleLogout);
}
