import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import LoadMore from './LoadMore';
import VideoGrid from './VideoGrid';
import { browseMoreRequested, browseRequested, liveRequested, recommendationsRequested } from './videosSlice';

const LIVE_REFRESH_MS = 30_000;

export default function BrowsePage() {
  const dispatch = useAppDispatch();
  const { browse, browseHasMore, browseLoading, error, live, loadingMore, recommended, recommendedSource, trending } =
    useAppSelector((s) => s.videos);
  const authStatus = useAppSelector((s) => s.auth.status);
  const authSettled = authStatus === 'authenticated' || authStatus === 'anonymous';

  useEffect(() => {
    dispatch(browseRequested());
  }, [dispatch]);

  useEffect(() => {
    dispatch(liveRequested());
    const timer = setInterval(() => dispatch(liveRequested()), LIVE_REFRESH_MS);
    return () => clearInterval(timer);
  }, [dispatch]);

  // After login state settles: only then does the request carry who's asking.
  useEffect(() => {
    if (authSettled) dispatch(recommendationsRequested());
  }, [dispatch, authSettled, authStatus]);

  return (
    <div className="browse">
      {live && live.viewersNow > 0 && (
        <p className="live-count">
          <span className="live-dot" aria-hidden="true" />
          {live.viewersNow} watching now
        </p>
      )}
      {live && live.trending.length > 0 && (
        <section>
          <h2>Trending in the last hour</h2>
          <VideoGrid videos={live.trending} />
        </section>
      )}
      {recommendedSource === 'personalized' && recommended.length > 0 && (
        <section>
          <h2>Recommended for you</h2>
          <VideoGrid videos={recommended.slice(0, 8)} />
        </section>
      )}
      {trending.length > 0 && (
        <section>
          <h2>Trending</h2>
          <VideoGrid videos={trending.slice(0, 8)} />
        </section>
      )}
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
        {browseHasMore && <LoadMore loading={loadingMore} onClick={() => dispatch(browseMoreRequested())} />}
      </section>
    </div>
  );
}
