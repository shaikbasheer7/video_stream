import { useAppDispatch, useAppSelector } from '../../app/store';
import { AUTO, qualitySelected, qualityLabel } from './playerSlice';

export default function QualityMenu() {
  const dispatch = useAppDispatch();
  const { levels, selected, current, native, buffering } = useAppSelector((s) => s.player);

  if (native) return <span className="muted small">Quality: automatic</span>;
  if (levels.length === 0) return null;

  const playing = levels.find((l) => l.index === current);
  const sorted = [...levels].sort((a, b) => b.height - a.height);
  return (
    <div className="quality-menu">
      <label>
        Quality
        <select value={selected} onChange={(e) => dispatch(qualitySelected(Number(e.target.value)))}>
          <option value={AUTO}>Auto{selected === AUTO && playing ? ` (${qualityLabel(playing)})` : ''}</option>
          {sorted.map((level) => (
            <option key={level.index} value={level.index}>
              {qualityLabel(level)}
            </option>
          ))}
        </select>
      </label>
      {buffering && <span className="muted small">Buffering…</span>}
    </div>
  );
}
