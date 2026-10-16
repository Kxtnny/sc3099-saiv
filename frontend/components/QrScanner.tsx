'use client';

import { useEffect, useRef } from 'react';
import { useCameraStream } from '@/lib/camera';

interface Props {
  onScan: (value: string) => void;
  /** Called if the camera cannot be used, so the caller can fall back to typing. */
  onUnavailable?: (reason: string) => void;
}

// Minimal typing for the BarcodeDetector API (not yet in lib.dom.d.ts).
interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}
declare global {
  interface Window {
    BarcodeDetector?: new (opts?: { formats?: string[] }) => BarcodeDetectorLike;
  }
}

const SCAN_INTERVAL_MS = 200;

/**
 * Live QR scanner. Uses the browser's BarcodeDetector where it exists and
 * falls back to jsQR (loaded on demand) elsewhere, e.g. Firefox and desktop Safari.
 */
export default function QrScanner({ onScan, onUnavailable }: Props) {
  const { videoRef, ready, error } = useCameraStream('environment');
  const doneRef = useRef(false);

  useEffect(() => {
    if (error) onUnavailable?.(error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  useEffect(() => {
    if (!ready) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const canvas = document.createElement('canvas');

    (async () => {
      const detector = window.BarcodeDetector ? new window.BarcodeDetector({ formats: ['qr_code'] }) : null;
      const jsQR = detector ? null : (await import('jsqr')).default;

      const tick = async () => {
        if (stopped || doneRef.current) return;
        const video = videoRef.current;
        if (video && video.videoWidth) {
          try {
            let value: string | undefined;
            if (detector) {
              value = (await detector.detect(video))[0]?.rawValue;
            } else if (jsQR) {
              canvas.width = video.videoWidth;
              canvas.height = video.videoHeight;
              const ctx = canvas.getContext('2d', { willReadFrequently: true });
              if (ctx) {
                ctx.drawImage(video, 0, 0);
                const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
                value = jsQR(img.data, img.width, img.height)?.data;
              }
            }
            if (value && value.trim() && !stopped) {
              doneRef.current = true;
              onScan(value.trim());
              return;
            }
          } catch {
            // A bad frame is not fatal; try the next one.
          }
        }
        timer = setTimeout(tick, SCAN_INTERVAL_MS);
      };
      tick();
    })();

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  if (error) return null;

  return (
    <div className="relative mx-auto w-full max-w-sm">
      <video ref={videoRef} autoPlay playsInline muted className="w-full rounded-md bg-black" />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 m-auto h-2/3 aspect-square rounded-lg border-2 border-white/80"
      />
      {!ready && <p className="mt-2 text-center text-sm text-gray-500">Starting camera…</p>}
    </div>
  );
}
