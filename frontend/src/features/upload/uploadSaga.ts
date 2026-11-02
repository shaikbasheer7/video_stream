import type { PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { buffers, END, eventChannel, type EventChannel, type Task } from 'redux-saga';
import { call, cancel, cancelled, delay, fork, join, put, race, retry, take } from 'redux-saga/effects';
import { api, errorMessage } from '../../app/api';
import type { CompletedPart, CreateVideoResponse, Video } from '../../types/api';
import { myVideosRequested } from '../videos/videosSlice';
import {
  encodingFinished,
  uploadCancelled,
  uploadCompleting,
  uploadFailed,
  uploadProgress,
  uploadRequested,
  uploadReset,
  uploadStarted,
  uploadSucceeded,
  type UploadRequest,
} from './uploadSlice';

export const POLL_INTERVAL_MS = 3000;

/** Poll the video until encoding finishes. Network blips are ignored; polling just continues. */
export function* pollUntilEncoded(videoId: string) {
  while (true) {
    yield delay(POLL_INTERVAL_MS);
    try {
      const { data }: { data: Video } = yield call(api.get, `/videos/${videoId}/`);
      if (data.status === 'ready' || data.status === 'failed') {
        yield put(encodingFinished(data));
        yield put(myVideosRequested());
        return;
      }
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        yield put(uploadFailed('This video was deleted.'));
        return;
      }
    }
  }
}

type PutEvent = { loaded: number } | { etag: string } | { error: unknown };

// Plain axios, not `api`: presigned URLs must not carry our Authorization header or cookies.
function putChannel(url: string, body: Blob, headers: Record<string, string>, signal: AbortSignal) {
  return eventChannel<PutEvent>((emit) => {
    axios
      .put(url, body, { headers, signal, onUploadProgress: (e) => emit({ loaded: e.loaded }) })
      .then((res) => emit({ etag: String(res.headers['etag'] ?? '') }))
      .catch((error) => emit({ error }))
      .finally(() => emit(END));
    return () => {};
    // Buffered: without it, events emitted while the saga is busy (including the final ETag) are lost.
  }, buffers.expanding<PutEvent>(16));
}

/** PUT one blob to S3, reporting overall progress. Returns the ETag. */
function* putWithProgress(
  url: string,
  body: Blob,
  headers: Record<string, string>,
  signal: AbortSignal,
  bytesBefore: number,
  totalBytes: number,
) {
  const channel: EventChannel<PutEvent> = yield call(putChannel, url, body, headers, signal);
  let lastPercent = -1;
  try {
    while (true) {
      const event: PutEvent = yield take(channel);
      if ('loaded' in event) {
        const percent = Math.floor(((bytesBefore + event.loaded) / totalBytes) * 100);
        if (percent !== lastPercent) {
          lastPercent = percent;
          yield put(uploadProgress(Math.min(percent, 99)));
        }
      } else if ('etag' in event) {
        return event.etag;
      } else {
        throw event.error;
      }
    }
  } finally {
    channel.close();
  }
}

export function* runUpload({ file, contentType, title, description }: UploadRequest) {
  const controller = new AbortController();
  let videoId: string | null = null;
  let uploaded = false; // after this, cancelling only stops polling; it never deletes the video
  try {
    const { data }: { data: CreateVideoResponse } = yield call(api.post, '/videos/', {
      title,
      description,
      filename: file.name,
      size: file.size,
      content_type: contentType,
    });
    videoId = data.video.id;
    yield put(uploadStarted(videoId));

    const { upload } = data;
    let parts: CompletedPart[] | undefined;
    if (upload.method === 'single') {
      yield retry(3, 1000, putWithProgress, upload.url, file, upload.headers, controller.signal, 0, file.size);
    } else {
      parts = [];
      // Sequential parts keep memory flat and progress simple; parallelism can come later.
      for (const part of upload.parts) {
        const start = (part.part_number - 1) * upload.part_size;
        const chunk = file.slice(start, start + upload.part_size);
        const etag: string = yield retry(3, 1000, putWithProgress, part.url, chunk, {}, controller.signal, start, file.size);
        if (!etag) throw new Error('Storage did not return an ETag (check the bucket CORS ExposeHeaders).');
        parts.push({ part_number: part.part_number, etag });
      }
    }

    yield put(uploadCompleting());
    const { data: video }: { data: Video } = yield retry(3, 2000, api.post, `/videos/${videoId}/complete/`, { parts });
    uploaded = true;
    yield put(uploadSucceeded(video));
    yield put(myVideosRequested());
    yield call(pollUntilEncoded, videoId);
  } catch (error) {
    yield put(uploadFailed(errorMessage(error)));
  } finally {
    if (((yield cancelled()) as boolean) && !uploaded) {
      controller.abort();
      // Drop the half-finished video (and its multipart upload) on the server.
      if (videoId) {
        try {
          yield call(api.delete, `/videos/${videoId}/`);
        } catch {
          // The bucket lifecycle rule still cleans up abandoned multipart uploads.
        }
      }
    }
  }
}

export default function* uploadSaga() {
  while (true) {
    const action: PayloadAction<UploadRequest> = yield take(uploadRequested.type);
    const task: Task = yield fork(runUpload, action.payload);
    // "Upload another" (reset) during encoding stops polling so the next upload can start.
    const { stop } = yield race({ stop: take([uploadCancelled.type, uploadReset.type]), finished: join(task) });
    if (stop) yield cancel(task);
  }
}
