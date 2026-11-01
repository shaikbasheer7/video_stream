import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import VideoGrid from './VideoGrid';
import { feedRequested } from './videosSlice';

/** New videos from creators you follow (filled by the feed subscriber). */
export default function FeedPage() {
  const dispatch = useAppDispatch();
  const { feed, feedLoading, error } = useAppSelector((s) => s.videos);

  useEffect(() => {
    dispatch(feedRequested());
  }, [dispatch]);

  return (
    <section>
      <div className="page-header">
        <h1>Following</h1>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {feedLoading && feed.length === 0 && <p className="muted">Loading…</p>}
      {!feedLoading && feed.length === 0 && !error && (
        <div className="card empty">
          <p>New videos from creators you follow show up here.</p>
          <Link to="/">Find someone to follow</Link>
        </div>
      )}
      <VideoGrid videos={feed} />
    </section>
  );
}
