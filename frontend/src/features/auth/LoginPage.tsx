import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import { loginRequested } from './authSlice';

export default function LoginPage() {
  const dispatch = useAppDispatch();
  const { status, error } = useAppSelector((s) => s.auth);
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  if (status === 'authenticated') return <Navigate to={from} replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    dispatch(loginRequested({ email, password }));
  };

  return (
    <form className="card auth-form" onSubmit={onSubmit}>
      <h1>Log in</h1>
      {error && <p className="error" role="alert">{error}</p>}
      <label>
        Email
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <button type="submit" disabled={status === 'loading'}>
        {status === 'loading' ? 'Logging in…' : 'Log in'}
      </button>
      <p className="muted">
        No account? <Link to="/register">Create one</Link>
      </p>
    </form>
  );
}
