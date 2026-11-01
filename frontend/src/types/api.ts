export interface User {
  id: number;
  email: string;
  display_name: string;
  is_staff: boolean;
  created_at: string;
}

export interface LoginResponse {
  access: string;
  user: User;
}

export interface RefreshResponse {
  access: string;
}

export interface Credentials {
  email: string;
  password: string;
}

export interface RegisterPayload extends Credentials {
  display_name: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type VideoStatus = 'uploading' | 'uploaded' | 'processing' | 'ready' | 'failed';

export interface Rendition {
  quality: '480p' | '720p' | '1080p';
  width: number;
  height: number;
  bitrate_kbps: number;
}

export interface Video {
  id: string;
  title: string;
  description: string;
  status: VideoStatus;
  owner: string;
  owner_id: number;
  is_owner: boolean;
  original_filename: string;
  size_bytes: number;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  error_message: string;
  thumbnail_url: string | null;
  renditions: Rendition[];
  created_at: string;
  updated_at: string;
  // Only on GET /videos/{id}/ for ready videos; the response also sets the CDN cookies.
  playback?: { hls_url: string; expires_at: string };
  // Only on GET /videos/{id}/ for logged-in viewers.
  is_following?: boolean;
  resume_position_sec?: number | null;
}

export interface AppNotification {
  id: string;
  type: 'video.ready' | 'video.failed';
  video_id: string;
  title: string;
  error: string;
  read: boolean;
  created_at: string;
}

export interface SingleUpload {
  method: 'single';
  url: string;
  headers: Record<string, string>;
  expires_in: number;
}

export interface MultipartUpload {
  method: 'multipart';
  part_size: number;
  parts: { part_number: number; url: string }[];
  expires_in: number;
}

export interface CreateVideoResponse {
  video: Video;
  upload: SingleUpload | MultipartUpload;
}

export interface CompletedPart {
  part_number: number;
  etag: string;
}
