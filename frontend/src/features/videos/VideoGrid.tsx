import { Link } from 'react-router-dom';
import type { Video } from '../../types/api';
import { formatDuration, snippetParts } from './format';

export default function VideoGrid({ videos }: { videos: Video[] }) {
  return (
    <ul className="video-grid">
      {videos.map((video) => (
        <li key={video.id}>
          <Link to={`/watch/${video.id}`} className="video-card">
            <div className="card-thumb">
              {video.thumbnail_url && <img src={video.thumbnail_url} alt="" loading="lazy" />}
              {video.duration_sec != null && <span className="duration">{formatDuration(video.duration_sec)}</span>}
            </div>
            <strong>{video.title}</strong>
            <span className="muted small">{video.owner}</span>
            {video.snippet && (
              <span className="muted small snippet">
                {snippetParts(video.snippet).map((part, index) =>
                  part.match ? <mark key={index}>{part.text}</mark> : part.text,
                )}
              </span>
            )}
          </Link>
        </li>
      ))}
    </ul>
  );
}
