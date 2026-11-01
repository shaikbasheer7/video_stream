import Hls, { ErrorTypes, Events } from 'hls.js';
import { useEffect, useRef, type RefObject } from 'react';
import { useAppDispatch, useAppSelector } from '../../app/store';
import { playbackEvent } from '../events/eventsSaga';
import { PlaybackTracker } from '../events/tracker';
import {
  AUTO,
  bufferingChanged,
  levelsLoaded,
  levelSwitched,
  nativePlayback,
  playerFailed,
  playerReset,
  positionUpdated,
} from './playerSlice';

interface Props {
  videoId: string;
  src: string;
  poster?: string | null;
  /** Where to start (resume), in seconds. */
  startPosition?: number | null;
  /** Changes whenever the API re-issues the CDN cookies (e.g. expires_at). */
  sessionKey: string;
  /** Called when the CDN answers 403: the cookies expired. Re-fetching the video renews them. */
  onAccessExpired: () => void;
  /** Lets the page control the element (e.g. "Start over"). */
  videoRef: RefObject<HTMLVideoElement>;
}

const MAX_MEDIA_RECOVERIES = 2;

export default function HlsPlayer({ videoId, src, poster, startPosition, sessionKey, onAccessExpired, videoRef }: Props) {
  const dispatch = useAppDispatch();
  const selected = useAppSelector((s) => s.player.selected);
  const hlsRef = useRef<Hls | null>(null);
  const trackerRef = useRef<PlaybackTracker | null>(null);
  const waitingForAccess = useRef(false);
  const positionRef = useRef(-1);
  const selectedRef = useRef(selected);
  const startRef = useRef(startPosition ?? null);
  const onAccessExpiredRef = useRef(onAccessExpired);
  useEffect(() => {
    onAccessExpiredRef.current = onAccessExpired;
  }, [onAccessExpired]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    dispatch(playerReset());
    // One tracker (and session_id) per video load.
    const tracker = new PlaybackTracker(videoId, (event) => dispatch(playbackEvent(event)));
    trackerRef.current = tracker;
    const start = startRef.current;

    if (Hls.isSupported()) {
      const hls = new Hls({
        startPosition: start ?? -1,
        // Cookies must accompany every playlist/segment request, also when the CDN is another (sub)domain.
        xhrSetup: (xhr) => {
          xhr.withCredentials = true;
        },
      });
      hlsRef.current = hls;
      let mediaRecoveries = 0;

      hls.on(Events.MANIFEST_PARSED, (_e, data) => {
        dispatch(levelsLoaded(data.levels.map((level, index) => ({ index, height: level.height, bitrate: level.bitrate }))));
      });
      hls.on(Events.LEVEL_SWITCHED, (_e, data) => {
        dispatch(levelSwitched(data.level));
        const height = hls.levels[data.level]?.height;
        if (height) tracker.onQualityChange(`${height}p`, selectedRef.current === AUTO, video.currentTime);
      });
      hls.on(Events.ERROR, (_e, data) => {
        // A 403 from the CDN means the cookies expired. hls.js often treats it as non-fatal and quietly
        // falls back to another quality, so react to it whether or not it is fatal.
        if (data.type === ErrorTypes.NETWORK_ERROR && data.response?.code === 403) {
          if (!waitingForAccess.current) {
            waitingForAccess.current = true;
            onAccessExpiredRef.current();
          }
          return;
        }
        if (!data.fatal) return;
        if (data.type === ErrorTypes.NETWORK_ERROR) {
          hls.startLoad(); // transient: keep trying from the current position
        } else if (data.type === ErrorTypes.MEDIA_ERROR && mediaRecoveries < MAX_MEDIA_RECOVERIES) {
          mediaRecoveries += 1;
          hls.recoverMediaError();
        } else {
          dispatch(playerFailed('This video could not be played.'));
          hls.destroy();
        }
      });
      hls.loadSource(src);
      hls.attachMedia(video);
      return () => {
        hls.destroy();
        hlsRef.current = null;
        trackerRef.current = null;
      };
    }

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari / iOS: native HLS sends cookies itself and picks the quality on its own.
      dispatch(nativePlayback());
      const seekToStart = () => {
        if (start) video.currentTime = start;
      };
      video.addEventListener('loadedmetadata', seekToStart, { once: true });
      video.src = src;
      return () => {
        video.removeEventListener('loadedmetadata', seekToStart);
        video.removeAttribute('src');
        video.load();
        trackerRef.current = null;
      };
    }

    dispatch(playerFailed('This browser cannot play HLS video.'));
  }, [videoId, src, dispatch, videoRef]);

  // Fresh cookies arrived after a 403: resume loading where playback is, with the viewer's quality choice.
  useEffect(() => {
    const hls = hlsRef.current;
    if (waitingForAccess.current && hls) {
      waitingForAccess.current = false;
      hls.startLoad(hls.media?.currentTime ?? -1);
      hls.currentLevel = selectedRef.current;
    }
  }, [sessionKey]);

  // Manual quality choice (-1 = automatic adaptive bitrate).
  useEffect(() => {
    selectedRef.current = selected;
    if (hlsRef.current) hlsRef.current.currentLevel = selected;
  }, [selected]);

  const tracker = () => trackerRef.current;
  return (
    <video
      ref={videoRef}
      className="player-video"
      controls
      playsInline
      poster={poster ?? undefined}
      onPlay={(e) => tracker()?.onPlay(e.currentTarget.currentTime)}
      onPause={(e) => tracker()?.onPause(e.currentTarget.currentTime, e.currentTarget.ended)}
      onSeeking={() => tracker()?.onSeeking()}
      onSeeked={(e) => tracker()?.onSeeked(e.currentTarget.currentTime)}
      onWaiting={() => {
        dispatch(bufferingChanged(true));
        tracker()?.onWaiting();
      }}
      onPlaying={(e) => {
        dispatch(bufferingChanged(false));
        tracker()?.onPlaying(e.currentTarget.currentTime);
      }}
      onTimeUpdate={(e) => {
        const v = e.currentTarget;
        tracker()?.onTimeUpdate(v.currentTime, v.duration, v.paused);
        const second = Math.floor(v.currentTime);
        if (second !== positionRef.current) {
          positionRef.current = second;
          dispatch(positionUpdated(second));
        }
      }}
    />
  );
}
