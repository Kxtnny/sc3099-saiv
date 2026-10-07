'use client';

import { useState } from 'react';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { ensureDeviceRegistered } from '@/lib/device';
import { getCurrentPosition } from '@/lib/geolocation';
import SessionPicker, { SessionSummary } from './SessionPicker';
import CameraCapture from './CameraCapture';

type Step = 'select' | 'qr' | 'camera' | 'submitting' | 'result';

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

  function reset() {
    setStep('select');
    setSession(null);
    setQrCode('');
    setResult(null);
    setError(null);
  }

  async function handleCapture(livenessImage: string) {
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
        liveness_challenge_response: livenessImage,
        ...(session.qr_code_enabled ? { qr_code: qrCode.trim() } : {}),
      });
      setResult(data);
      setStep('result');
    } catch (err) {
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
      <form
        className="max-w-sm space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (qrCode.trim()) setStep('camera');
        }}
      >
        <p className="text-sm text-gray-500">Checking in to: {session.name}</p>
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
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={!qrCode.trim()}
            className="rounded-md bg-blue-600 text-white text-sm px-4 py-2 disabled:opacity-50"
          >
            Continue
          </button>
          <button type="button" onClick={reset} className="text-sm underline">
            Cancel
          </button>
        </div>
      </form>
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
