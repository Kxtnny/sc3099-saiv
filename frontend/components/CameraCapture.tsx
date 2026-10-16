'use client';

import { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { grabFrame, useCameraStream } from '@/lib/camera';

/** What the backend needs for the challenge flow of POST /checkins/. */
export interface LivenessCapture {
  challengeId: string;
  challengeType: string;
  /** Base64 JPEG frames (no data-URL prefix), oldest first. */
  frames: string[];
}

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
const PROMPTS: Record<string, string> = {
  blink: 'Blink slowly, twice',
  head_turn: 'Turn your head slightly left, then back',
  mouth_open: 'Open your mouth, then close it',
};
const FALLBACK_PROMPT = 'Follow the prompt on screen';

// Frames are sent to the backend in a single request (5 to 45 allowed), so
// keep them small: about 24 frames of ~50 KB each.
const GET_READY_MS = 1200; // look straight: the first frame is used for face match
const RECORD_MS = 3000;
const FRAME_INTERVAL_MS = 125;
const MIN_FRAMES = 5;
const MAX_FRAMES = 45;
const FRAME_QUALITY = 0.7;

type Phase = 'loading' | 'ready' | 'recording';

export default function CameraCapture({ onCapture, onCancel }: Props) {
  const { videoRef, ready, error: cameraError, stop } = useCameraStream('user');
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [challengeError, setChallengeError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [phase, setPhase] = useState<Phase>('loading');
  const [progress, setProgress] = useState(0);

  // Ask for a fresh one-time challenge once the camera is running, so its
  // 60 second lifetime is not spent waiting on the permission prompt.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setChallenge(null);
    setChallengeError(null);
    setPhase('loading');

    api
      .get<Challenge>('/checkins/liveness-challenge')
      .then((res) => {
        if (!cancelled) setChallenge(res.data);
      })
      .catch((err) => {
        if (cancelled) return;
        setChallengeError(
          isAxiosError(err) && err.response?.status === 503
            ? 'The liveness service is unavailable right now. Try again in a moment.'
            : 'Could not start the liveness check. Check your connection and try again.'
        );
      });

    return () => {
      cancelled = true;
    };
  }, [ready, attempt]);

  // Look straight, then record frames while the prompt is on screen.
  useEffect(() => {
    if (!challenge) return;
    const { challenge_id, challenge_type } = challenge;
    const frames: string[] = [];
    let interval: ReturnType<typeof setInterval> | undefined;
    let progressTimer: ReturnType<typeof setInterval> | undefined;
    let finishTimer: ReturnType<typeof setTimeout> | undefined;

    setPhase('ready');
    setProgress(0);

    const startTimer = setTimeout(() => {
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
        if (frames.length < MIN_FRAMES) {
          // The video never produced enough pictures (e.g. the tab was in the background).
          setChallenge(null);
          setChallengeError('We could not capture enough video. Keep this tab open and try again.');
          return;
        }
        stop();
        onCapture({ challengeId: challenge_id, challengeType: challenge_type, frames });
      }, RECORD_MS);
    }, GET_READY_MS);

    return () => {
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
        {(!ready || phase === 'loading') && <p className="text-sm text-gray-500">Starting liveness check…</p>}
        {phase === 'ready' && <p className="text-sm font-medium text-gray-800">Look straight at the camera</p>}
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
