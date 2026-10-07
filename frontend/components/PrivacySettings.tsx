'use client';

import { useState } from 'react';
import { useAuth } from '@/lib/auth';

type ConsentKey = 'camera_consent' | 'geolocation_consent';

const CONSENTS: { key: ConsentKey; title: string; description: string }[] = [
  {
    key: 'camera_consent',
    title: 'Camera',
    description: 'Used only at the moment of check-in for the liveness and face check.',
  },
  {
    key: 'geolocation_consent',
    title: 'Location',
    description: 'Used only during check-in to confirm you’re within range of the venue.',
  },
];

/** Lets a student withdraw consent they gave in the ConsentGate. Withdrawing
 * sets the flag to false on the backend, which brings the gate back before
 * the next check-in, so opting back in uses the same explained flow. */
export default function PrivacySettings({ onBack }: { onBack: () => void }) {
  const { user, updateConsent } = useAuth();
  const [busy, setBusy] = useState<ConsentKey | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function withdraw(key: ConsentKey) {
    setBusy(key);
    setError(null);
    try {
      await updateConsent({ [key]: false });
    } catch {
      setError('Could not update your consent. Check your connection and try again.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-md space-y-4">
      <p className="text-sm text-gray-600">
        You can withdraw consent at any time. Check-in needs both, so you&rsquo;ll be asked again
        before your next check-in.
      </p>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {CONSENTS.map(({ key, title, description }) => {
        const granted = !!user?.[key];
        return (
          <div key={key} className="rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-medium">{title}</h3>
              <span className={`text-xs font-medium ${granted ? 'text-green-700' : 'text-gray-500'}`}>
                {granted ? 'Allowed' : 'Not allowed'}
              </span>
            </div>
            <p className="text-sm text-gray-600 mt-1">{description}</p>
            {granted && (
              <button
                disabled={busy !== null}
                onClick={() => withdraw(key)}
                className="mt-3 rounded-md border border-red-300 text-red-700 text-sm px-4 py-2 disabled:opacity-50"
              >
                {busy === key ? 'Withdrawing…' : 'Withdraw consent'}
              </button>
            )}
          </div>
        );
      })}

      <p className="text-xs text-gray-500">
        This updates your SAIV account. To also stop this site from using your camera or location,
        change the site&rsquo;s permissions in your browser settings.
      </p>

      <button onClick={onBack} className="text-sm underline">
        Back to check-in
      </button>
    </div>
  );
}
