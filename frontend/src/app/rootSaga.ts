import { all, fork } from 'redux-saga/effects';
import authSaga from '../features/auth/authSaga';
import eventsSaga from '../features/events/eventsSaga';
import notificationsSaga from '../features/notifications/notificationsSaga';
import uploadSaga from '../features/upload/uploadSaga';
import videosSaga from '../features/videos/videosSaga';

export default function* rootSaga() {
  yield all([fork(authSaga), fork(uploadSaga), fork(videosSaga), fork(eventsSaga), fork(notificationsSaga)]);
}
