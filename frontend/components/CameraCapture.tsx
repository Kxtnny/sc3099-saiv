'use client';

import { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { grabFrame, useCameraStream } from '@/lib/camera';

/**
 * What the check-in sends to the backend.
 * - challenge: the normal flow (server-issued challenge plus a frame sequence).
 * - passive: used when the liveness service is down, so the backend can run
 *   passive liveness itself or flag the check-in for review instead of rejecting it.
 * `faceFrame` is one high-quality frame used for face matching.
 */
export type LivenessCapture =
  | {
      kind: 'challenge';
      challengeId: string;
      challengeType: string;
      /** Base64 JPEG frames (no data-URL prefix), oldest first. */
      frames: string[];
      faceFrame: string;
    }
  | { kind: 'passive'; faceFrame: string };

interface Challenge {
  challenge_id: string;
  challenge_type: string;
  expires_in: number;
}

interface Props {
  onCapture: (capture: LivenessCapture) => void;
  onCancel: () => void;
}

// The server picks the action, so the prompt must follow challenge_type.
// The face service needs the action held across several frames (eyes shut in
// 2 in a row; head turned or mouth open in 3), so the wording asks for a
// clear, held movement rather than a quick or slight one.
const PROMPTS: Record<string, string> = {
  blink: 'Close your eyes for a moment, then open them. Do it twice.',
  head_turn: 'Turn your head to the left and hold, then face the camera',
  mouth_open: 'Open your mouth wide and hold, then close it',
};
const FALLBACK_PROMPT = 'Follow the prompt on screen';

// Frames are sent to the backend in a single request (5 to 45 allowed), so
// keep them small: up to 45 frames of ~50 KB each (about 2.2 MB).
const GET_READY_MS = 3000; // countdown with the action shown, so recording isn't spent reading it
const RECORD_MS = 4500;
const FRAME_INTERVAL_MS = 100; // 10 fps: a short eye closure still spans 2 frames
const MIN_FRAMES = 5;
const MAX_FRAMES = 45;
const FRAME_QUALITY = 0.7;
const FACE_FRAME_QUALITY = 0.9; // the single frame used for face matching

type Phase = 'loading' | 'ready' | 'recording' | 'fallback';

export default function CameraCapture({ onCapture, onCancel }: Props) {
  const { videoRef, ready, error: cameraError, stop } = useCameraStream('user');
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [challengeError, setChallengeError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [phase, setPhase] = useState<Phase>('loading');
  const [progress, setProgress] = useState(0);
  const [countdown, setCountdown] = useState(0);
  const [fallback, setFallback] = useState(false);

  // Ask for a fresh one-time challenge once the camera is running, so its
  // 60 second lifetime is not spent waiting on the permission prompt.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setChallenge(null);
    setChallengeError(null);
    setFallback(false);
    setPhase('loading');

    api
      .get<Challenge>('/checkins/liveness-challenge')
      .then((res) => {
        if (!cancelled) setChallenge(res.data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (isAxiosError(err) && err.response?.status === 503) {
          // The face service is down. Don't block the student: send one photo
          // and let the backend run passive liveness, or flag the check-in for
          // review if it is still unavailable.
          setFallback(true);
          return;
        }
        setChallengeError('Could not start the liveness check. Check your connection and try again.');
      });

    return () => {
      cancelled = true;
    };
  }, [ready, attempt]);

  // Liveness service down: look straight, then take a single photo.
  useEffect(() => {
    if (!fallback) return;
    setPhase('fallback');
    const timer = setTimeout(() => {
      const faceFrame = grabFrame(videoRef.current, FACE_FRAME_QUALITY);
      if (!faceFrame) {
        setFallback(false);
        setChallengeError('We could not capture a photo. Keep this tab open and try again.');
        return;
      }
      stop();
      onCapture({ kind: 'passive', faceFrame });
    }, GET_READY_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fallback]);

  // Count down with the action shown, then record frames while the student does it.
  useEffect(() => {
    if (!challenge) return;
    const { challenge_id, challenge_type } = challenge;
    const frames: string[] = [];
    let interval: ReturnType<typeof setInterval> | undefined;
    let progressTimer: ReturnType<typeof setInterval> | undefined;
    let finishTimer: ReturnType<typeof setTimeout> | undefined;

    setPhase('ready');
    setProgress(0);
    setCountdown(Math.ceil(GET_READY_MS / 1000));
    const countdownTimer = setInterval(() => setCountdown((n) => Math.max(1, n - 1)), 1000);

    const startTimer = setTimeout(() => {
      clearInterval(countdownTimer);
      // One clear frame at the end of the "look straight" step, before any
      // movement, for face matching. The recorded frames are lower quality.
      const faceFrame = grabFrame(videoRef.current, FACE_FRAME_QUALITY);
      setPhase('recording');
      const startedAt = Date.now();

      const take = () => {
        if (frames.length >= MAX_FRAMES) return;
        const frame = grabFrame(videoRef.current, FRAME_QUALITY);
        if (frame) frames.push(frame);
      };
      take();
      interval = setInterval(take, FRAME_INTERVAL_MS);
      progressTimer = setInterval(
        () => setProgress(Math.min(1, (Date.now() - startedAt) / RECORD_MS)),
        100
      );

      finishTimer = setTimeout(() => {
        clearInterval(interval);
        clearInterval(progressTimer);
        if (frames.length < MIN_FRAMES || !faceFrame) {
          // The video never produced enough pictures (e.g. the tab was in the background).
          setChallenge(null);
          setChallengeError('We could not capture enough video. Keep this tab open and try again.');
          return;
        }
        stop();
        onCapture({ kind: 'challenge', challengeId: challenge_id, challengeType: challenge_type, frames, faceFrame });
      }, RECORD_MS);
    }, GET_READY_MS);

    return () => {
      clearInterval(countdownTimer);
      clearTimeout(startTimer);
      clearTimeout(finishTimer);
      clearInterval(interval);
      clearInterval(progressTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challenge]);

  const error = cameraError ?? challengeError;
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 max-w-md">
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
        <div className="mt-3 flex gap-4">
          {!cameraError && (
            <button onClick={() => setAttempt((n) => n + 1)} className="text-sm underline text-red-700">
              Try again
            </button>
          )}
          <button onClick={onCancel} className="text-sm underline text-red-700">
            Cancel
          </button>
        </div>
      </div>
    );
  }

  const prompt = challenge ? PROMPTS[challenge.challenge_type] ?? FALLBACK_PROMPT : null;

  return (
    <div className="rounded-lg border border-gray-200 p-4 max-w-md">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="w-full max-w-sm rounded-md bg-black scale-x-[-1] mx-auto"
      />
      <div className="mt-3 text-center" aria-live="polite">
        {(!ready || (phase === 'loading' && !fallback)) && <p className="text-sm text-gray-500">Starting liveness check…</p>}
        {phase === 'ready' && (
          <>
            {/* Keep the face straight until recording: the face-match frame is taken as it starts. */}
            <p className="text-sm font-medium text-gray-800">Look straight at the camera</p>
            <p className="mt-1 text-sm text-gray-600">
              Next: <span className="font-medium text-gray-900">{prompt}</span>
            </p>
            <p className="mt-2 text-3xl font-semibold text-blue-600 tabular-nums">{countdown}</p>
          </>
        )}
        {phase === 'fallback' && (
          <>
            <p className="text-sm font-medium text-gray-800">Look straight at the camera</p>
            <p className="mt-1 text-xs text-gray-500">
              The liveness check is unavailable right now, so we&rsquo;ll take a photo instead. Your check-in may be sent for review.
            </p>
          </>
        )}
        {phase === 'recording' && (
          <>
            <p className="text-lg font-semibold text-gray-900">{prompt}</p>
            <div className="mt-2 h-1.5 w-full max-w-xs mx-auto rounded bg-gray-200 overflow-hidden">
              <div className="h-full bg-blue-600" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          </>
        )}
      </div>
      <button onClick={onCancel} className="mt-3 block mx-auto text-xs text-gray-500 underline">
        Cancel
      </button>
    </div>
  );
}
