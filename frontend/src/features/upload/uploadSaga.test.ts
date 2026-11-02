import type { UnknownAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { runSaga } from 'redux-saga';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../app/api';
import { runUpload } from './uploadSaga';
import reducer, { uploadRequested, type UploadState } from './uploadSlice';

const video = { id: 'vid-1', status: 'uploaded' };

/** Runs the saga with fake timers so polling delays pass instantly. */
async function run(file: File) {
  vi.useFakeTimers();
  const dispatched: UnknownAction[] = [];
  let state: UploadState = reducer(undefined, uploadRequested({ file, contentType: 'video/mp4', title: 'T', description: '' }));
  const task = runSaga(
    {
      dispatch: (action: UnknownAction) => {
        dispatched.push(action);
        state = reducer(state, action);
      },
      getState: () => ({}),
    },
    runUpload,
    { file, contentType: 'video/mp4', title: 'T', description: '' },
  );
  await vi.advanceTimersByTimeAsync(60_000);
  await task.toPromise();
  return { dispatched, state };
}

/** GET /videos/{id}/ answers with each status in turn (the last one repeats). */
function mockPolling(...statuses: string[]) {
  let call = 0;
  return vi.spyOn(api, 'get').mockImplementation(async () => {
    const status = statuses[Math.min(call++, statuses.length - 1)];
    return { data: { id: 'vid-1', status, error_message: status === 'failed' ? 'The file has no video stream.' : '' } };
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('runUpload', () => {
  it('uploads a small file with one PUT, then completes', async () => {
    const post = vi.spyOn(api, 'post').mockImplementation(async (url: string) => {
      if (url === '/videos/') {
        return {
          data: {
            video: { id: 'vid-1' },
            upload: { method: 'single', url: 'https://s3/put', headers: { 'Content-Type': 'video/mp4' } },
          },
        };
      }
      return { data: video };
    });
    const put = vi.spyOn(axios, 'put').mockImplementation(async (_url, _body, config) => {
      config?.onUploadProgress?.({ loaded: 5, total: 10, bytes: 5, lengthComputable: true });
      return { headers: { etag: '"abc"' } };
    });
    const get = mockPolling('processing', 'processing', 'ready');

    const { state, dispatched } = await run(new File(['0123456789'], 'clip.mp4'));

    expect(put).toHaveBeenCalledWith('https://s3/put', expect.any(File), expect.objectContaining({ headers: { 'Content-Type': 'video/mp4' } }));
    expect(post).toHaveBeenLastCalledWith('/videos/vid-1/complete/', { parts: undefined });
    expect(dispatched.map((a) => a.type)).toContain('upload/uploadProgress');
    expect(get).toHaveBeenCalledTimes(3);
    expect(state).toMatchObject({ stage: 'ready', videoId: 'vid-1', progress: 100 });
  });

  it('shows the encoder error when encoding fails', async () => {
    vi.spyOn(api, 'post').mockImplementation(async (url: string) =>
      url === '/videos/'
        ? { data: { video: { id: 'vid-1' }, upload: { method: 'single', url: 'https://s3/put', headers: {} } } }
        : { data: video },
    );
    vi.spyOn(axios, 'put').mockResolvedValue({ headers: { etag: '"abc"' } });
    mockPolling('processing', 'failed');

    const { state } = await run(new File(['x'], 'clip.mp4'));
    expect(state).toMatchObject({ stage: 'failed', error: 'The file has no video stream.' });
  });

  it('uploads parts in order and sends their ETags on complete', async () => {
    const post = vi.spyOn(api, 'post').mockImplementation(async (url: string) => {
      if (url === '/videos/') {
        return {
          data: {
            video: { id: 'vid-1' },
            upload: {
              method: 'multipart',
              part_size: 4,
              parts: [1, 2, 3].map((n) => ({ part_number: n, url: `https://s3/part/${n}` })),
            },
          },
        };
      }
      return { data: video };
    });
    const sizes: number[] = [];
    vi.spyOn(axios, 'put').mockImplementation(async (url: string, body: unknown) => {
      sizes.push((body as Blob).size);
      return { headers: { etag: `"etag-${url.split('/').pop()}"` } };
    });
    mockPolling('ready');

    const { state } = await run(new File(['0123456789'], 'clip.mp4'));

    expect(sizes).toEqual([4, 4, 2]);
    expect(post).toHaveBeenLastCalledWith('/videos/vid-1/complete/', {
      parts: [
        { part_number: 1, etag: '"etag-1"' },
        { part_number: 2, etag: '"etag-2"' },
        { part_number: 3, etag: '"etag-3"' },
      ],
    });
    expect(state.stage).toBe('ready');
  });

  it('reports a server validation error', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(
      Object.assign(new axios.AxiosError('Bad'), { response: { status: 400, data: { size: ['Files are limited to 5 GB.'] } } }),
    );
    const { state } = await run(new File(['x'], 'clip.mp4'));
    expect(state).toMatchObject({ stage: 'failed', error: 'Files are limited to 5 GB.' });
  });
});
