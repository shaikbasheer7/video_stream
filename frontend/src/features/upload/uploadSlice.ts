import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { Video } from '../../types/api';

export type UploadStage =
  | 'idle'
  | 'requesting' // asking the API for presigned URLs
  | 'uploading' // bytes going straight to S3
  | 'completing' // API verifies the object and publishes video.uploaded
  | 'processing' // encoding; the saga polls until ready / failed
  | 'ready'
  | 'failed'
  | 'cancelled';

export interface UploadState {
  stage: UploadStage;
  fileName: string | null;
  progress: number; // 0–100
  videoId: string | null;
  error: string | null;
}

export interface UploadRequest {
  file: File;
  contentType: string;
  title: string;
  description: string;
}

const initialState: UploadState = { stage: 'idle', fileName: null, progress: 0, videoId: null, error: null };

const uploadSlice = createSlice({
  name: 'upload',
  initialState,
  reducers: {
    // The File stays in the action (handled by the saga) and is never stored in state.
    uploadRequested(_state, action: PayloadAction<UploadRequest>) {
      return { ...initialState, stage: 'requesting', fileName: action.payload.file.name };
    },
    uploadStarted(state, action: PayloadAction<string>) {
      state.stage = 'uploading';
      state.videoId = action.payload;
    },
    uploadProgress(state, action: PayloadAction<number>) {
      state.progress = action.payload;
    },
    uploadCompleting(state) {
      state.stage = 'completing';
      state.progress = 100;
    },
    uploadSucceeded(state, action: PayloadAction<Video>) {
      state.stage = 'processing';
      state.videoId = action.payload.id;
    },
    encodingFinished(state, action: PayloadAction<Video>) {
      if (action.payload.status === 'ready') {
        state.stage = 'ready';
      } else {
        state.stage = 'failed';
        state.error = action.payload.error_message || 'Encoding failed.';
      }
    },
    uploadFailed(state, action: PayloadAction<string>) {
      state.stage = 'failed';
      state.error = action.payload;
    },
    uploadCancelled(state) {
      state.stage = 'cancelled';
    },
    uploadReset() {
      return initialState;
    },
  },
});

export const {
  uploadRequested,
  uploadStarted,
  uploadProgress,
  uploadCompleting,
  uploadSucceeded,
  encodingFinished,
  uploadFailed,
  uploadCancelled,
  uploadReset,
} = uploadSlice.actions;

export const isUploadActive = (stage: UploadStage) =>
  stage === 'requesting' || stage === 'uploading' || stage === 'completing';

export default uploadSlice.reducer;
