import { call, delay, put, race, take, takeEvery } from 'redux-saga/effects';
import { api } from '../../app/api';
import type { AppNotification } from '../../types/api';
import { loggedOut, loginSucceeded } from '../auth/authSlice';
import { notificationsCleared, notificationsLoaded, notificationsOpened } from './notificationsSlice';

export const POLL_MS = 30_000;

function* pollWhileLoggedIn() {
  while (true) {
    try {
      const { data }: { data: { unread: number; results: AppNotification[] } } = yield call(api.get, '/notifications/');
      yield put(notificationsLoaded({ unread: data.unread, items: data.results }));
    } catch {
      // keep the last known list; try again next round
    }
    yield delay(POLL_MS);
  }
}

function* markRead() {
  try {
    yield call(api.post, '/notifications/read/');
  } catch {
    // next poll restores the real count
  }
}

export default function* notificationsSaga() {
  yield takeEvery(notificationsOpened.type, markRead);
  while (true) {
    yield take(loginSucceeded.type);
    yield race({ poll: call(pollWhileLoggedIn), logout: take(loggedOut.type) });
    yield put(notificationsCleared());
  }
}
