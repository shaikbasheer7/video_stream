import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import VideoGrid from './VideoGrid';
import { browseRequested } from './videosSlice';

export default function BrowsePage() {
  const dispatch = useAppDispatch();
  const { browse, browseLoading, error } = useAppSelector((s) => s.videos);

  useEffect(() => {
    dispatch(browseRequested());
  }, [dispatch]);

  return (
    <section>
      <div className="page-header">
        <h1>Browse</h1>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {browseLoading && browse.length === 0 && <p className="muted">Loading…</p>}
      {!browseLoading && browse.length === 0 && !error && (
        <div className="card empty">
          <p>No videos yet.</p>
          <Link to="/upload">Upload the first one</Link>
        </div>
      )}
      <VideoGrid videos={browse} />
    </section>
  );
}
