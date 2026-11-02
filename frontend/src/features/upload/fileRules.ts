// Keep in sync with backend/videos/uploads.py (ALLOWED_TYPES) and MAX_UPLOAD_BYTES.
export const CONTENT_TYPES: Record<string, string> = {
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  mkv: 'video/x-matroska',
  webm: 'video/webm',
};
export const MAX_UPLOAD_BYTES = 5 * 1024 ** 3;
export const ACCEPT = Object.keys(CONTENT_TYPES)
  .map((ext) => `.${ext}`)
  .join(',');

export type FileCheck = { ok: true; contentType: string } | { ok: false; error: string };

/** Checked before any request is made. The server validates again. */
export function checkFile(file: Pick<File, 'name' | 'size'>): FileCheck {
  const extension = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : '';
  const contentType = CONTENT_TYPES[extension];
  if (!contentType) return { ok: false, error: 'Choose an MP4, MOV, MKV or WebM video.' };
  if (file.size === 0) return { ok: false, error: 'This file is empty.' };
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, error: 'Videos are limited to 5 GB.' };
  // Browsers report MKV/MOV types inconsistently, so the extension decides.
  return { ok: true, contentType };
}

export function formatBytes(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
