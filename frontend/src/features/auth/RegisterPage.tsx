import { useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import { registerRequested } from './authSlice';

export default function RegisterPage() {
  const dispatch = useAppDispatch();
  const { status, error } = useAppSelector((s) => s.auth);
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  if (status === 'authenticated') return <Navigate to="/" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    dispatch(registerRequested({ email, password, display_name: displayName }));
  };

  return (
    <form className="card auth-form" onSubmit={onSubmit}>
      <h1>Create account</h1>
      {error && <p className="error" role="alert">{error}</p>}
      <label>
        Display name
        <input autoComplete="nickname" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </label>
      <label>
        Email
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <button type="submit" disabled={status === 'loading'}>
        {status === 'loading' ? 'Creating…' : 'Create account'}
      </button>
      <p className="muted">
        Already registered? <Link to="/login">Log in</Link>
      </p>
    </form>
  );
}
