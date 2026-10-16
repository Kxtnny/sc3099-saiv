'use client';

import { RefObject, useEffect, useRef, useState } from 'react';

export interface CameraState {
  videoRef: RefObject<HTMLVideoElement>;
  /** True once the stream is attached and playing. */
  ready: boolean;
  /** A student-readable message if the camera could not be opened. */
  error: string | null;
  /** Stop the camera now (it is also stopped automatically on unmount). */
  stop: () => void;
}

/**
 * Opens the camera and attaches it to `videoRef`. The stream is always
 * released on unmount, so no screen can leave the camera light on.
 */
export function useCameraStream(facing: 'user' | 'environment' = 'user'): CameraState {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser cannot access the camera. Camera access also needs a secure (https) connection.');
      return;
    }

    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: { ideal: facing }, width: { ideal: 640 }, height: { ideal: 480 } },
      })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        setReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err?.name === 'NotAllowedError'
            ? 'Camera permission was denied. Allow camera access for this site in your browser settings, then try again.'
            : 'Could not access the camera on this device.'
        );
      });

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, [facing]);

  function stop() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setReady(false);
  }

  return { videoRef, ready, error, stop };
}

/**
 * Grabs the current video frame as a base64 JPEG without the data-URL prefix,
 * which is the format the backend expects. Returns null if the video has no
 * picture yet.
 */
export function grabFrame(video: HTMLVideoElement | null, quality = 0.9): string | null {
  if (!video || !video.videoWidth || !video.videoHeight) return null;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0);
  return canvas.toDataURL('image/jpeg', quality).replace(/^data:image\/\w+;base64,/, '');
}
