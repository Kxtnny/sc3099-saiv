'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { ensureDeviceRegistered } from '@/lib/device';
import { getCurrentPosition } from '@/lib/geolocation';
import { enqueueCheckin, listQueuedCheckins, syncQueuedCheckins, watchConnectivity } from '@/lib/offlineQueue';
import SessionPicker, { SessionSummary } from './SessionPicker';
import CameraCapture from './CameraCapture';

type Step = 'select' | 'camera' | 'submitting' | 'result' | 'queued';

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

export default function CheckinFlow() {
  const [step, setStep] = useState<Step>('select');
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CheckinResult | null>(null);
  const [queuedCount, setQueuedCount] = useState(0);

  useEffect(() => {
    listQueuedCheckins().then((items) => setQueuedCount(items.length));
    const stopWatching = watchConnectivity(async () => {
      const { remaining } = await syncQueuedCheckins();
      setQueuedCount(remaining);
    });
    return stopWatching;
  }, []);

  function reset() {
    setStep('select');
    setSession(null);
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

      const payload = {
        session_id: session.id,
        latitude: position.latitude,
        longitude: position.longitude,
        location_accuracy_meters: position.accuracy,
        device_fingerprint: deviceFingerprint,
        liveness_challenge_response: livenessImage,
      };

      const { data } = await api.post<CheckinResult>('/checkins/', payload);
      setResult(data);
      setStep('result');
    } catch (err: any) {
      if (!err?.response) {
        // No response at all — we're almost certainly offline. Queue it.
        const deviceFingerprint = await ensureDeviceRegistered().catch(() => 'unknown');
        try {
          const position = await getCurrentPosition();
          await enqueueCheckin({
            session_id: session.id,
            latitude: position.latitude,
            longitude: position.longitude,
            location_accuracy_meters: position.accuracy,
            device_fingerprint: deviceFingerprint,
            liveness_challenge_response: livenessImage,
          });
          const items = await listQueuedCheckins();
          setQueuedCount(items.length);
          setStep('queued');
          return;
        } catch {
          setError('Could not determine your location. Check-in was not queued.');
          setStep('select');
          return;
        }
      }
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Check-in failed.');
      setStep('select');
    }
  }

  if (step === 'select') {
    return (
      <div>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        {queuedCount > 0 && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2 mb-3">
            {queuedCount} check-in{queuedCount > 1 ? 's are' : ' is'} queued offline and will sync
            automatically once you&rsquo;re back online.
          </p>
        )}
        <SessionPicker
          onSelect={(s) => {
            setSession(s);
            setStep('camera');
          }}
        />
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

  if (step === 'queued') {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 max-w-sm">
        <p className="font-medium text-amber-900">Saved offline</p>
        <p className="text-sm text-amber-800 mt-1">
          You appear to be offline. Your check-in was saved and will be submitted automatically as
          soon as your connection returns.
        </p>
        <button onClick={reset} className="mt-3 text-sm underline text-amber-900">
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
