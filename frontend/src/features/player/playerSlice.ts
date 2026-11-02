import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface QualityLevel {
  index: number; // hls.js level index
  height: number;
  bitrate: number;
}

export const AUTO = -1;

export interface PlayerState {
  levels: QualityLevel[];
  selected: number; // AUTO or a level index chosen by the viewer
  current: number | null; // level actually playing (hls.js LEVEL_SWITCHED)
  native: boolean; // Safari/iOS native HLS: the browser picks quality, no manual choice
  buffering: boolean;
  position: number; // seconds, whole
  error: string | null;
}

const initialState: PlayerState = {
  levels: [],
  selected: AUTO,
  current: null,
  native: false,
  buffering: false,
  position: 0,
  error: null,
};

const playerSlice = createSlice({
  name: 'player',
  initialState,
  reducers: {
    playerReset() {
      return initialState;
    },
    levelsLoaded(state, action: PayloadAction<QualityLevel[]>) {
      state.levels = action.payload;
      state.native = false;
    },
    nativePlayback(state) {
      state.native = true;
      state.levels = [];
    },
    qualitySelected(state, action: PayloadAction<number>) {
      state.selected = action.payload;
    },
    levelSwitched(state, action: PayloadAction<number>) {
      state.current = action.payload;
    },
    bufferingChanged(state, action: PayloadAction<boolean>) {
      state.buffering = action.payload;
    },
    positionUpdated(state, action: PayloadAction<number>) {
      state.position = action.payload;
    },
    playerFailed(state, action: PayloadAction<string>) {
      state.error = action.payload;
    },
  },
});

export const {
  playerReset,
  levelsLoaded,
  nativePlayback,
  qualitySelected,
  levelSwitched,
  bufferingChanged,
  positionUpdated,
  playerFailed,
} = playerSlice.actions;

export function qualityLabel(level: QualityLevel | undefined): string {
  return level ? `${level.height}p` : '';
}

export default playerSlice.reducer;
