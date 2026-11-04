import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import { formatDuration, searchPath } from '../videos/format';
import VideoGrid from '../videos/VideoGrid';
import { followRequested, similarRequested, videoRequested, videoViewersRequested } from '../videos/videosSlice';
import HlsPlayer from './HlsPlayer';
import QualityMenu from './QualityMenu';

const LIVE_REFRESH_MS = 30_000;

export default function PlayerPage() {
  const { id = '' } = useParams();
  const dispatch = useAppDispatch();
  const { current: video, currentLoading, currentError, similar, videoViewers } = useAppSelector((s) => s.videos);
  const authStatus = useAppSelector((s) => s.auth.status);
  const loggedIn = authStatus === 'authenticated';
  const authSettled = authStatus === 'authenticated' || authStatus === 'anonymous';
  const playerError = useAppSelector((s) => s.player.error);
  const videoRef = useRef<HTMLVideoElement>(null);
  // The video whose "Resuming from…" chip was dismissed (so it reappears for the next video).
  const [resumeDismissedFor, setResumeDismissedFor] = useState<string | null>(null);
  const renewAccess = useCallback(() => dispatch(videoRequested(id)), [dispatch, id]);

  // Wait until we know who's watching: logged-in viewers get their resume position and follow state.
  useEffect(() => {
    if (authSettled) dispatch(videoRequested(id));
  }, [dispatch, id, authSettled, loggedIn]);

  useEffect(() => {
    dispatch(similarRequested(id));
  }, [dispatch, id]);

  useEffect(() => {
    dispatch(videoViewersRequested(id));
    const timer = setInterval(() => dispatch(videoViewersRequested(id)), LIVE_REFRESH_MS);
    return () => clearInterval(timer);
  }, [dispatch, id]);

  if (currentError) {
    return (
      <section className="card empty">
        <p>{currentError}</p>
        <Link to="/">Browse videos</Link>
      </section>
    );
  }
  if (!video || video.id !== id) return <p className="centered muted">{currentLoading || !authSettled ? 'Loading…' : ''}</p>;

  // Stable per video: the reducer keeps the first resume position when the same video is re-fetched.
  const resumeAt = video.resume_position_sec ?? null;
  const startOver = () => {
    if (videoRef.current) videoRef.current.currentTime = 0;
    setResumeDismissedFor(id);
  };

  return (
    <article className="watch">
      <div className="player-frame">
        {video.playback ? (
          <HlsPlayer
            key={video.id}
            ref={videoRef}
            videoId={video.id}
            src={video.playback.hls_url}
            poster={video.thumbnail_url}
            startPosition={resumeAt}
            sessionKey={video.playback.expires_at}
            onAccessExpired={renewAccess}
            subtitles={video.subtitles}
          />
        ) : (
          <div className="player-placeholder">
            {video.status === 'failed' ? `Encoding failed: ${video.error_message}` : 'This video is still being processed.'}
          </div>
        )}
      </div>
      {resumeAt !== null && resumeDismissedFor !== id && (
        <p className="resume-chip small">
          Resuming from {formatDuration(resumeAt)} ·{' '}
          <button className="link-button" onClick={startOver}>
            Start over
          </button>
        </p>
      )}
      {playerError && (
        <p className="error" role="alert">
          {playerError}
        </p>
      )}
      <div className="watch-header">
        <h1>{video.title}</h1>
        {video.playback && <QualityMenu />}
      </div>
      <div className="watch-meta">
        <p className="muted small">
          {video.owner} · {new Date(video.created_at).toLocaleDateString()}
          {video.duration_sec != null && ` · ${formatDuration(video.duration_sec)}`}
          {videoViewers?.videoId === id && videoViewers.viewers > 0 && ` · ${videoViewers.viewers} watching now`}
        </p>
        {loggedIn && !video.is_owner && video.is_following !== undefined && (
          <button
            className={video.is_following ? 'secondary' : undefined}
            onClick={() => dispatch(followRequested({ userId: video.owner_id, follow: !video.is_following }))}
          >
            {video.is_following ? 'Following' : `Follow ${video.owner}`}
          </button>
        )}
      </div>
      {video.description && <p className="description">{video.description}</p>}
      {video.tags && video.tags.length > 0 && (
        <ul className="tag-list" aria-label="Tags">
          {video.tags.map((tag) => (
            <li key={tag}>
              <Link to={searchPath(tag)} className="tag">
                {tag}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {similar?.videoId === id && similar.items.length > 0 && (
        <section className="similar">
          <h2>{similar.source === 'similar' ? 'Similar videos' : 'Trending'}</h2>
          <VideoGrid videos={similar.items} />
        </section>
      )}
    </article>
  );
}
