import { lazy, Suspense, useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAppDispatch } from './app/store';
import Layout from './components/Layout';
import LoginPage from './features/auth/LoginPage';
import ProtectedRoute from './features/auth/ProtectedRoute';
import RegisterPage from './features/auth/RegisterPage';
import { sessionRestoreRequested } from './features/auth/authSlice';
import UploadPage from './features/upload/UploadPage';
import BrowsePage from './features/videos/BrowsePage';
import FeedPage from './features/videos/FeedPage';
import LibraryPage from './features/videos/LibraryPage';

// hls.js is large; load it only when someone opens a video.
const PlayerPage = lazy(() => import('./features/player/PlayerPage'));

export default function App() {
  const dispatch = useAppDispatch();

  useEffect(() => {
    dispatch(sessionRestoreRequested());
  }, [dispatch]);

  return (
    <Routes>
      <Route element={<Layout />}>
        {/* Public: anyone can browse and watch ready videos. */}
        <Route path="/" element={<BrowsePage />} />
        <Route
          path="/watch/:id"
          element={
            <Suspense fallback={<p className="centered muted">Loading…</p>}>
              <PlayerPage />
            </Suspense>
          }
        />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/my" element={<LibraryPage />} />
          <Route path="/following" element={<FeedPage />} />
          <Route path="/upload" element={<UploadPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
