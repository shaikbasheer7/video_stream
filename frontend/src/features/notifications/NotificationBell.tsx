import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import { notificationsOpened } from './notificationsSlice';

export default function NotificationBell() {
  const dispatch = useAppDispatch();
  const { items, unread } = useAppSelector((s) => s.notifications);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = () => {
    if (!open && unread > 0) dispatch(notificationsOpened());
    setOpen(!open);
  };

  return (
    <div className="bell" ref={ref}>
      <button
        className="secondary bell-button"
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        onClick={toggle}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z"
          />
        </svg>
        {unread > 0 && <span className="bell-count">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel card" role="dialog" aria-label="Notifications">
          {items.length === 0 && <p className="muted small">No notifications yet.</p>}
          <ul>
            {items.map((n) => (
              <li key={n.id}>
                <Link to={n.type === 'video.ready' ? `/watch/${n.video_id}` : '/my'} onClick={() => setOpen(false)}>
                  <strong>{n.title}</strong>{' '}
                  {n.type === 'video.ready' ? 'is ready to watch.' : `failed: ${n.error || 'encoding error'}`}
                </Link>
                <span className="muted small">{new Date(n.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
