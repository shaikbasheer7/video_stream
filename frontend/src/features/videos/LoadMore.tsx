interface Props {
  loading: boolean;
  onClick: () => void;
}

export default function LoadMore({ loading, onClick }: Props) {
  return (
    <div className="load-more">
      <button className="secondary" disabled={loading} onClick={onClick}>
        {loading ? 'Loading…' : 'Load more'}
      </button>
    </div>
  );
}
