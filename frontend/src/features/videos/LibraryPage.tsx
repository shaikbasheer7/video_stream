import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import type { Video, VideoStatus } from '../../types/api';
import { formatBytes } from '../upload/fileRules';
import { formatDuration } from './format';
import { myVideosRequested, videoDeleteRequested } from './videosSlice';

const STATUS_LABELS: Record<VideoStatus, string> = {
  uploading: 'Uploading',
  uploaded: 'Queued',
  processing: 'Encoding',
  ready: 'Ready',
  failed: 'Failed',
};
const PENDING: VideoStatus[] = ['uploaded', 'processing'];
const REFRESH_MS = 5000;

function details(video: Video): string {
  if (video.status === 'ready') {
    const parts = [video.duration_sec != null ? formatDuration(video.duration_sec) : null];
    parts.push(video.renditions.map((r) => r.quality).join(' · '));
    return parts.filter(Boolean).join(' · ');
  }
  return `${video.original_filename} · ${formatBytes(video.size_bytes)}`;
}

/** Your uploads in every state. Ready ones link to the player. */
export default function LibraryPage() {
  const dispatch = useAppDispatch();
  const { mine, loading, error } = useAppSelector((s) => s.videos);
  const hasPending = mine.some((v) => PENDING.includes(v.status));

  useEffect(() => {
    dispatch(myVideosRequested());
  }, [dispatch]);

  // Refresh while anything is still encoding (Django Channels could push this later).
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => dispatch(myVideosRequested()), REFRESH_MS);
    return () => clearInterval(timer);
  }, [dispatch, hasPending]);

  const onDelete = (id: string, title: string) => {
    if (window.confirm(`Delete "${title}"? This cannot be undone.`)) dispatch(videoDeleteRequested(id));
  };

  return (
    <section>
      <div className="page-header">
        <h1>My videos</h1>
        <Link to="/upload" className="button-link">
          Upload video
        </Link>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && mine.length === 0 && <p className="muted">Loading…</p>}
      {!loading && mine.length === 0 && !error && (
        <div className="card empty">
          <p>You haven't uploaded anything yet.</p>
        </div>
      )}
      {mine.length > 0 && (
        <ul className="video-list">
          {mine.map((video) => (
            <li key={video.id} className="card video-row">
              <div className="thumb">
                {video.thumbnail_url ? (
                  <img src={video.thumbnail_url} alt="" loading="lazy" />
                ) : (
                  <span className="thumb-placeholder" aria-hidden="true" />
                )}
              </div>
              <div className="video-info">
                {video.status === 'ready' ? (
                  <Link to={`/watch/${video.id}`} className="title-link">
                    <strong>{video.title}</strong>
                  </Link>
                ) : (
                  <strong>{video.title}</strong>
                )}
                <p className="muted small">
                  {details(video)} · {new Date(video.created_at).toLocaleDateString()}
                </p>
                {video.status === 'failed' && video.error_message && <p className="error small">{video.error_message}</p>}
              </div>
              <span className={`badge badge-${video.status}`}>{STATUS_LABELS[video.status]}</span>
              <button className="secondary" onClick={() => onDelete(video.id, video.title)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
