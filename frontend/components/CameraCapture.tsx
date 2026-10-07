'use client';

import { useEffect, useRef, useState } from 'react';

const CHALLENGE_STEPS = [
  { label: 'Look straight at the camera', seconds: 2 },
  { label: 'Blink slowly', seconds: 2 },
  { label: 'Turn your head slightly left, then back', seconds: 2 },
];

interface Props {
  onCapture: (base64Jpeg: string) => void;
  onCancel: () => void;
}

export default function CameraCapture({ onCapture, onCancel }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
        setReady(true);
      })
      .catch((err) => {
        setError(
          err?.name === 'NotAllowedError'
            ? 'Camera permission was denied. You can retry or use a different sign-in method.'
            : 'Could not access the camera on this device.'
        );
      });

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  // Walk through the liveness prompts once the stream is ready.
  useEffect(() => {
    if (!ready || error) return;
    if (stepIndex >= CHALLENGE_STEPS.length) {
      capture();
      return;
    }
    const timer = setTimeout(() => setStepIndex((i) => i + 1), CHALLENGE_STEPS[stepIndex].seconds * 1000);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, stepIndex, error]);

  function capture() {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
    const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, '');
    streamRef.current?.getTracks().forEach((track) => track.stop());
    onCapture(base64);
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4">
        <p className="text-sm text-red-700">{error}</p>
        <button onClick={onCancel} className="mt-3 text-sm underline text-red-700">
          Cancel
        </button>
      </div>
    );
  }

  const currentStep = stepIndex < CHALLENGE_STEPS.length ? CHALLENGE_STEPS[stepIndex] : null;

  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="w-full max-w-sm rounded-md bg-black scale-x-[-1] mx-auto"
      />
      <div className="mt-3 text-center">
        {!ready && <p className="text-sm text-gray-500">Starting camera…</p>}
        {ready && currentStep && (
          <p className="text-sm font-medium text-gray-800">{currentStep.label}</p>
        )}
        {ready && !currentStep && <p className="text-sm text-gray-500">Capturing…</p>}
      </div>
      <button onClick={onCancel} className="mt-3 block mx-auto text-xs text-gray-500 underline">
        Cancel
      </button>
    </div>
  );
}
