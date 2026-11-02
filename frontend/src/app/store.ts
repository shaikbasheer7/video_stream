import { configureStore } from '@reduxjs/toolkit';
import { useDispatch, useSelector } from 'react-redux';
import createSagaMiddleware from 'redux-saga';
import authReducer from '../features/auth/authSlice';
import notificationsReducer from '../features/notifications/notificationsSlice';
import playerReducer from '../features/player/playerSlice';
import uploadReducer, { uploadRequested } from '../features/upload/uploadSlice';
import videosReducer from '../features/videos/videosSlice';
import { setupInterceptors } from './api';
import rootSaga from './rootSaga';

const sagaMiddleware = createSagaMiddleware();

export const store = configureStore({
  reducer: {
    auth: authReducer,
    upload: uploadReducer,
    videos: videosReducer,
    player: playerReducer,
    notifications: notificationsReducer,
  },
  middleware: (getDefault) =>
    getDefault({
      thunk: false,
      // uploadRequested carries the File for the saga; it never reaches state.
      serializableCheck: { ignoredActions: [uploadRequested.type] },
    }).concat(sagaMiddleware),
});

setupInterceptors(store);
sagaMiddleware.run(rootSaga);

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
