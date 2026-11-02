import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAppSelector } from '../../app/store';

export default function ProtectedRoute() {
  const status = useAppSelector((s) => s.auth.status);
  const location = useLocation();

  if (status === 'idle' || status === 'loading') return <p className="centered muted">Loading…</p>;
  if (status !== 'authenticated') return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}
