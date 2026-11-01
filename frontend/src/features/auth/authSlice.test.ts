import { describe, expect, it } from 'vitest';
import reducer, { authFailed, loggedOut, loginRequested, loginSucceeded, tokenRefreshed } from './authSlice';

const user = { id: 1, email: 'a@example.com', display_name: 'A', is_staff: false, created_at: '2026-11-01T00:00:00Z' };

describe('authSlice', () => {
  it('starts idle with no token', () => {
    expect(reducer(undefined, { type: '@@init' })).toEqual({ user: null, accessToken: null, status: 'idle', error: null });
  });

  it('stores user and access token on login', () => {
    let state = reducer(undefined, loginRequested({ email: user.email, password: 'x' }));
    expect(state.status).toBe('loading');
    state = reducer(state, loginSucceeded({ access: 'tok', user }));
    expect(state).toMatchObject({ status: 'authenticated', accessToken: 'tok', user });
  });

  it('replaces the token on refresh and clears everything on logout', () => {
    let state = reducer(undefined, loginSucceeded({ access: 'old', user }));
    state = reducer(state, tokenRefreshed('new'));
    expect(state.accessToken).toBe('new');
    state = reducer(state, loggedOut());
    expect(state).toMatchObject({ status: 'anonymous', accessToken: null, user: null });
  });

  it('keeps the error message on failure', () => {
    const state = reducer(undefined, authFailed('Bad credentials'));
    expect(state).toMatchObject({ status: 'anonymous', error: 'Bad credentials' });
  });
});
