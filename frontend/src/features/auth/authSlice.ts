import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { Credentials, LoginResponse, RegisterPayload, User } from '../../types/api';

export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'anonymous';

export interface AuthState {
  user: User | null;
  // Access token lives in memory only; the refresh token is an httpOnly cookie.
  accessToken: string | null;
  status: AuthStatus;
  error: string | null;
}

const initialState: AuthState = { user: null, accessToken: null, status: 'idle', error: null };

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    sessionRestoreRequested(state) {
      state.status = 'loading';
    },
    loginRequested(state, _action: PayloadAction<Credentials>) {
      state.status = 'loading';
      state.error = null;
    },
    registerRequested(state, _action: PayloadAction<RegisterPayload>) {
      state.status = 'loading';
      state.error = null;
    },
    loginSucceeded(state, action: PayloadAction<LoginResponse>) {
      state.user = action.payload.user;
      state.accessToken = action.payload.access;
      state.status = 'authenticated';
      state.error = null;
    },
    authFailed(state, action: PayloadAction<string>) {
      state.user = null;
      state.accessToken = null;
      state.status = 'anonymous';
      state.error = action.payload;
    },
    tokenRefreshed(state, action: PayloadAction<string>) {
      state.accessToken = action.payload;
    },
    logoutRequested() {},
    loggedOut(state) {
      state.user = null;
      state.accessToken = null;
      state.status = 'anonymous';
      state.error = null;
    },
  },
});

export const {
  sessionRestoreRequested,
  loginRequested,
  registerRequested,
  loginSucceeded,
  authFailed,
  tokenRefreshed,
  logoutRequested,
  loggedOut,
} = authSlice.actions;

export default authSlice.reducer;
