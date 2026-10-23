'use client';

import { useState } from 'react';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { grabFrame, useCameraStream } from '@/lib/camera';

interface Props {
  /** Called after a successful enrollment. */
  onDone: () => void;
  /** Re-enrollment from settings: shows a Cancel button. */
  onCancel?: () => void;
  /** First-time enrollment: lets the student continue if the face service is down. */
  onSkip?: () => void;
}

function describeEnrollError(err: unknown): { message: string; serviceDown: boolean } {
  if (isAxiosError(err)) {
    if (!err.response) {
      return { message: 'Could not reach the server. Check your connection and try again.', serviceDown: false };
    }
    if (err.response.status === 503) {
      return {
        message: 'Face recognition is temporarily unavailable. Try again in a moment.',
        serviceDown: true,
      };
    }
    const detail = (err.response.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') {
      return { message: detail, serviceDown: false };
    }
  }
  return { message: 'Face enrollment failed. Please try again.', serviceDown: false };
}

/**
 * Captures one well-lit photo and sends it to POST /users/me/face/enroll.
 * The backend keeps only a hash of the face, never the image.
 */
export default function FaceEnrollment({ onDone, onCancel, onSkip }: Props) {
  const { refreshUser, markFaceEnrolled, user } = useAuth();
  const { videoRef, ready, error: cameraError, stop } = useCameraStream('user');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serviceDown, setServiceDown] = useState(false);

  const reenrolling = !!user?.face_enrolled;

  async function enroll() {
    const image = grabFrame(videoRef.current, 0.9);
    if (!image) {
      setError('The camera is not ready yet. Wait a moment and try again.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post('/users/me/face/enroll', { image });
      stop();
      // The server confirmed enrollment, so update the app state right away.
      // That moves the student on even if the profile refresh below fails.
      markFaceEnrolled();
      refreshUser().catch(() => {});
      onDone();
    } catch (err) {
      const { message, serviceDown: down } = describeEnrollError(err);
      setError(message);
      setServiceDown(down);
    } finally {
      setBusy(false);
    }
  }

  if (cameraError) {
    return (
      <div className="max-w-md rounded-lg border border-red-200 bg-red-50 p-4">
        <p className="text-sm text-red-700">{cameraError}</p>
        {onCancel && (
          <button onClick={onCancel} className="mt-3 text-sm underline text-red-700">
            Back
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-md space-y-4">
      <p className="text-sm text-gray-600">
        {reenrolling
          ? 'Take a new photo to replace your saved face template.'
          : 'Take one photo so SAIV can confirm it is really you at check-in. Only a mathematical template of your face is kept; the photo itself is discarded straight away.'}
      </p>

      <div className="relative mx-auto w-full max-w-sm">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full rounded-md bg-black scale-x-[-1]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 m-auto h-3/4 w-1/2 rounded-full border-2 border-dashed border-white/70"
        />
      </div>

      <ul className="text-xs text-gray-500 list-disc pl-5 space-y-1">
        <li>Face the camera directly, with your whole face inside the oval.</li>
        <li>Use even lighting, with no strong light behind you.</li>
        <li>Remove sunglasses, hats or masks.</li>
      </ul>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={enroll}
          disabled={!ready || busy}
          className="rounded-md bg-blue-600 text-white text-sm px-4 py-2 disabled:opacity-50"
        >
          {!ready ? 'Starting camera…' : busy ? 'Enrolling…' : reenrolling ? 'Capture & re-enroll' : 'Capture & enroll'}
        </button>
        {onCancel && (
          <button onClick={onCancel} disabled={busy} className="text-sm underline">
            Cancel
          </button>
        )}
        {onSkip && serviceDown && (
          <button onClick={onSkip} className="text-sm underline text-gray-600">
            Skip for now
          </button>
        )}
      </div>
    </div>
  );
}
