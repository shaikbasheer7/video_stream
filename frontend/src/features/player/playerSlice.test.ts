import { describe, expect, it } from 'vitest';
import { formatDuration } from '../videos/format';
import reducer, { AUTO, levelsLoaded, levelSwitched, nativePlayback, playerReset, qualitySelected } from './playerSlice';

const levels = [
  { index: 0, height: 480, bitrate: 1_640_000 },
  { index: 1, height: 720, bitrate: 3_360_000 },
];

describe('playerSlice', () => {
  it('starts on automatic quality', () => {
    expect(reducer(undefined, { type: '@@init' }).selected).toBe(AUTO);
  });

  it('tracks levels, the manual choice and the level actually playing', () => {
    let state = reducer(undefined, levelsLoaded(levels));
    state = reducer(state, qualitySelected(1));
    state = reducer(state, levelSwitched(1));
    expect(state).toMatchObject({ levels, selected: 1, current: 1, native: false });
  });

  it('native playback has no manual levels, and reset clears everything', () => {
    let state = reducer(reducer(undefined, levelsLoaded(levels)), nativePlayback());
    expect(state).toMatchObject({ native: true, levels: [] });
    state = reducer(state, playerReset());
    expect(state.native).toBe(false);
  });
});

describe('formatDuration', () => {
  it('formats minutes and hours', () => {
    expect(formatDuration(20)).toBe('0:20');
    expect(formatDuration(605.4)).toBe('10:05');
    expect(formatDuration(3725)).toBe('1:02:05');
  });
});
