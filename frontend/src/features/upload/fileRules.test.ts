import { describe, expect, it } from 'vitest';
import { checkFile, formatBytes, MAX_UPLOAD_BYTES } from './fileRules';

describe('checkFile', () => {
  it('maps the extension to the content type the server expects', () => {
    expect(checkFile({ name: 'Trip.MKV', size: 10 })).toEqual({ ok: true, contentType: 'video/x-matroska' });
    expect(checkFile({ name: 'clip.mov', size: 10 })).toEqual({ ok: true, contentType: 'video/quicktime' });
  });

  it('rejects other formats, empty files and files over the limit', () => {
    expect(checkFile({ name: 'notes.txt', size: 10 }).ok).toBe(false);
    expect(checkFile({ name: 'noextension', size: 10 }).ok).toBe(false);
    expect(checkFile({ name: 'a.mp4', size: 0 }).ok).toBe(false);
    expect(checkFile({ name: 'a.mp4', size: MAX_UPLOAD_BYTES + 1 }).ok).toBe(false);
  });
});

describe('formatBytes', () => {
  it('uses readable units', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(5 * 1024 ** 2)).toBe('5.0 MB');
  });
});
