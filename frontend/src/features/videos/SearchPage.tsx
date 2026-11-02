import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import VideoGrid from './VideoGrid';
import { searchRequested } from './videosSlice';

const MIN_QUERY_LENGTH = 2; // same as the API

export default function SearchPage() {
  const dispatch = useAppDispatch();
  const [params] = useSearchParams();
  const query = (params.get('q') ?? '').trim();
  const longEnough = query.length >= MIN_QUERY_LENGTH;
  const search = useAppSelector((s) => s.videos.search);
  // The first render of new words, before the effect below has asked for them.
  const settled = search.query === query && !search.loading;

  useEffect(() => {
    if (longEnough) dispatch(searchRequested(query));
  }, [dispatch, query, longEnough]);

  return (
    <section className="browse">
      <div className="page-header">
        <h1>{longEnough ? `Results for “${query}”` : 'Search'}</h1>
      </div>
      {!longEnough && <p className="muted">Type at least {MIN_QUERY_LENGTH} characters to search.</p>}
      {longEnough && !settled && search.results.length === 0 && <p className="muted">Searching…</p>}
      {longEnough && settled && search.error && (
        <p className="error" role="alert">
          {search.error}
        </p>
      )}
      {longEnough && settled && !search.error && search.results.length === 0 && (
        <div className="card empty">
          <p>No videos match “{query}”.</p>
        </div>
      )}
      {longEnough && search.query === query && <VideoGrid videos={search.results} />}
    </section>
  );
}
