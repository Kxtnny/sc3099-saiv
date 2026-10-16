'use client';

import { useState } from 'react';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { ensureDeviceRegistered } from '@/lib/device';
import { getCurrentPosition } from '@/lib/geolocation';
import SessionPicker, { SessionSummary } from './SessionPicker';
import CameraCapture, { LivenessCapture } from './CameraCapture';
import QrScanner from './QrScanner';

type Step = 'select' | 'qr' | 'camera' | 'submitting' | 'result' | 'already';

interface CheckinResult {
  status: 'pending' | 'approved' | 'flagged' | 'rejected';
  risk_score?: number;
}

const STATUS_COPY: Record<CheckinResult['status'], { label: string; className: string }> = {
  approved: { label: 'Checked in ✓', className: 'bg-green-50 border-green-300 text-green-800' },
  pending: { label: 'Check-in pending review', className: 'bg-yellow-50 border-yellow-300 text-yellow-800' },
  flagged: { label: 'Flagged for instructor review', className: 'bg-yellow-50 border-yellow-300 text-yellow-800' },
  rejected: { label: 'Check-in rejected', className: 'bg-red-50 border-red-300 text-red-800' },
};

function isGeolocationError(err: unknown): err is GeolocationPositionError {
  return typeof err === 'object' && err !== null && 'code' in err && 'PERMISSION_DENIED' in err;
}

/** The backend answers a repeat check-in with 400 "Already checked in to this session". */
function isAlreadyCheckedIn(err: unknown): boolean {
  if (!isAxiosError(err)) return false;
  const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
  return typeof detail === 'string' && detail.toLowerCase().startsWith('already checked in');
}

/** Turns whatever went wrong during check-in into a message the student can act on. */
function describeCheckinError(err: unknown): string {
  if (isGeolocationError(err)) {
    if (err.code === err.PERMISSION_DENIED) {
      return 'Location access is blocked. Allow location for this site in your browser settings, then try again.';
    }
    return 'Could not get your location. Move somewhere with better signal and try again.';
  }
  if (isAxiosError(err)) {
    if (!err.response) {
      // Check-ins are verified in real time (time window, location, liveness),
      // so they are never saved for later submission.
      return typeof navigator !== 'undefined' && !navigator.onLine
        ? 'You are offline. Reconnect and try again — check-ins can’t be saved for later.'
        : 'Could not reach the server. Try again in a moment.';
    }
    const detail = (err.response.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return 'Check-in failed.';
}

export default function CheckinFlow() {
  const [step, setStep] = useState<Step>('select');
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [qrCode, setQrCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CheckinResult | null>(null);
  const [scanning, setScanning] = useState(true);
  const [scanNote, setScanNote] = useState<string | null>(null);

  function reset() {
    setStep('select');
    setSession(null);
    setQrCode('');
    setScanning(true);
    setScanNote(null);
    setResult(null);
    setError(null);
  }

  async function handleCapture(liveness: LivenessCapture) {
    if (!session) return;
    setStep('submitting');
    setError(null);

    try {
      const [position, deviceFingerprint] = await Promise.all([
        getCurrentPosition(),
        ensureDeviceRegistered(),
      ]);

      const { data } = await api.post<CheckinResult>('/checkins/', {
        session_id: session.id,
        latitude: position.latitude,
        longitude: position.longitude,
        location_accuracy_meters: position.accuracy,
        device_fingerprint: deviceFingerprint,
        liveness_challenge_id: liveness.challengeId,
        liveness_challenge_type: liveness.challengeType,
        liveness_frames: liveness.frames,
        ...(session.qr_code_enabled ? { qr_code: qrCode.trim() } : {}),
      });
      setResult(data);
      setStep('result');
    } catch (err) {
      if (isAlreadyCheckedIn(err)) {
        setStep('already');
        return;
      }
      setError(describeCheckinError(err));
      setStep('select');
    }
  }

  if (step === 'select') {
    return (
      <div>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <SessionPicker
          onSelect={(s) => {
            setSession(s);
            setStep(s.qr_code_enabled ? 'qr' : 'camera');
          }}
        />
      </div>
    );
  }

  if (step === 'qr' && session) {
    return (
      <div className="max-w-sm space-y-3">
        <p className="text-sm text-gray-500">Checking in to: {session.name}</p>
        {scanning ? (
          <>
            <p className="text-sm font-medium">Point your camera at the QR code shown by your instructor</p>
            <QrScanner
              onScan={(value) => {
                setQrCode(value);
                setStep('camera');
              }}
              onUnavailable={(reason) => {
                setScanning(false);
                setScanNote(`${reason} You can type the code instead.`);
              }}
            />
            <div className="flex gap-4">
              <button type="button" onClick={() => setScanning(false)} className="text-sm underline">
                Type the code instead
              </button>
              <button type="button" onClick={reset} className="text-sm underline">
                Cancel
              </button>
            </div>
          </>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (qrCode.trim()) setStep('camera');
            }}
          >
            {scanNote && <p className="text-sm text-red-600">{scanNote}</p>}
            <label className="block text-sm font-medium" htmlFor="qr-code">
              Enter the code shown by your instructor
            </label>
            <input
              id="qr-code"
              value={qrCode}
              onChange={(e) => setQrCode(e.target.value)}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={!qrCode.trim()}
                className="rounded-md bg-blue-600 text-white text-sm px-4 py-2 disabled:opacity-50"
              >
                Continue
              </button>
              <button
                type="button"
                onClick={() => {
                  setScanNote(null);
                  setScanning(true);
                }}
                className="text-sm underline"
              >
                Scan QR code
              </button>
              <button type="button" onClick={reset} className="text-sm underline">
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    );
  }

  if (step === 'camera' && session) {
    return (
      <div>
        <p className="text-sm text-gray-500 mb-3">Checking in to: {session.name}</p>
        <CameraCapture onCapture={handleCapture} onCancel={reset} />
      </div>
    );
  }

  if (step === 'submitting') {
    return <p className="text-sm text-gray-500">Submitting check-in…</p>;
  }

  if (step === 'already') {
    // The backend allows one check-in per session whatever its outcome, so
    // the earlier attempt may have been flagged or rejected: don't claim success.
    return (
      <div role="status" className="rounded-lg border p-4 max-w-sm bg-blue-50 border-blue-300 text-blue-800">
        <p className="font-medium">Check-in already submitted</p>
        <p className="text-sm mt-1">
          {session ? `${session.name}: you` : 'You'} have already checked in to this session. See My
          check-ins for its status.
        </p>
        <button onClick={reset} className="mt-3 text-sm underline">
          Done
        </button>
      </div>
    );
  }

  if (step === 'result' && result) {
    const copy = STATUS_COPY[result.status];
    return (
      <div className={`rounded-lg border p-4 max-w-sm ${copy.className}`}>
        <p className="font-medium">{copy.label}</p>
        {typeof result.risk_score === 'number' && (
          <p className="text-sm mt-1">Risk score: {result.risk_score.toFixed(2)}</p>
        )}
        <button onClick={reset} className="mt-3 text-sm underline">
          Done
        </button>
      </div>
    );
  }

  return null;
}
