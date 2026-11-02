import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { searchPath } from './format';

export default function SearchBox() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const current = pathname === '/search' ? (params.get('q') ?? '') : '';
  const [text, setText] = useState(current);
  const [followed, setFollowed] = useState(current);

  // Follows the page: a tag link fills it in, and leaving the results empties it.
  if (followed !== current) {
    setFollowed(current);
    setText(current);
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const query = text.trim();
    if (query) navigate(searchPath(query));
  };

  return (
    <form className="search-box" role="search" onSubmit={submit}>
      <input
        type="search"
        aria-label="Search videos"
        placeholder="Search titles, tags and speech"
        maxLength={200}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
    </form>
  );
}
