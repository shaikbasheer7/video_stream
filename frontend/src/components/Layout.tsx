import { Link, NavLink, Outlet } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../app/store';
import { logoutRequested } from '../features/auth/authSlice';
import NotificationBell from '../features/notifications/NotificationBell';
import SearchBox from '../features/videos/SearchBox';

export default function Layout() {
  const dispatch = useAppDispatch();
  const { user, status } = useAppSelector((s) => s.auth);

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Streamline
        </Link>
        <nav className="topbar-nav">
          <NavLink to="/" end>
            Browse
          </NavLink>
          {user && <NavLink to="/following">Following</NavLink>}
          {user && <NavLink to="/my">My videos</NavLink>}
          {user && <NavLink to="/upload">Upload</NavLink>}
        </nav>
        <SearchBox />
        {user ? (
          <div className="topbar-user">
            <NotificationBell />
            <span className="muted">{user.display_name || user.email}</span>
            <button className="secondary" onClick={() => dispatch(logoutRequested())}>
              Log out
            </button>
          </div>
        ) : (
          status === 'anonymous' && (
            <div className="topbar-user">
              <Link to="/login">Log in</Link>
              <Link to="/register" className="button-link">
                Sign up
              </Link>
            </div>
          )
        )}
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}
