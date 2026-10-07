'use client';

import { useState } from 'react';
import { useAuth } from '@/lib/auth';
import { getCurrentPosition } from '@/lib/geolocation';

// Once both consents are recorded, the parent page swaps this gate for the
// check-in flow automatically, so there is no separate "Continue" step.
export default function ConsentGate() {
  const { user, updateConsent } = useAuth();
  const [busy, setBusy] = useState<'camera' | 'location' | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [locationError, setLocationError] = useState<string | null>(null);

  const cameraGranted = !!user?.camera_consent;
  const locationGranted = !!user?.geolocation_consent;

  async function grantCamera() {
    setBusy('camera');
    setCameraError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      stream.getTracks().forEach((t) => t.stop());
      await updateConsent({ camera_consent: true });
    } catch {
      setCameraError('Camera permission was denied. You can retry from your browser settings.');
    } finally {
      setBusy(null);
    }
  }

  async function grantLocation() {
    setBusy('location');
    setLocationError(null);
    try {
      await getCurrentPosition();
      await updateConsent({ geolocation_consent: true });
    } catch {
      setLocationError('Location permission was denied. You can retry from your browser settings.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-md space-y-4">
      <p className="text-sm text-gray-600">
        Before you can check in, SAIV needs two permissions. Nothing is requested until you tap
        &ldquo;Allow&rdquo; below, and you can revoke either at any time in your browser settings.
      </p>

      <div className="rounded-lg border border-gray-200 p-4">
        <h3 className="font-medium">Camera</h3>
        <p className="text-sm text-gray-600 mt-1">
          Used only at the moment of check-in to prove you&rsquo;re physically present (liveness
          check). No photo is stored — it&rsquo;s processed and discarded.
        </p>
        {cameraError && <p className="text-sm text-red-600 mt-2">{cameraError}</p>}
        <button
          disabled={cameraGranted || busy === 'camera'}
          onClick={grantCamera}
          className="mt-3 rounded-md bg-blue-600 text-white text-sm px-4 py-2 disabled:opacity-50"
        >
          {cameraGranted ? 'Camera enabled ✓' : busy === 'camera' ? 'Requesting…' : 'Allow camera'}
        </button>
      </div>

      <div className="rounded-lg border border-gray-200 p-4">
        <h3 className="font-medium">Location</h3>
        <p className="text-sm text-gray-600 mt-1">
          Used only during check-in to confirm you&rsquo;re within range of the venue.
        </p>
        {locationError && <p className="text-sm text-red-600 mt-2">{locationError}</p>}
        <button
          disabled={locationGranted || busy === 'location'}
          onClick={grantLocation}
          className="mt-3 rounded-md bg-blue-600 text-white text-sm px-4 py-2 disabled:opacity-50"
        >
          {locationGranted ? 'Location enabled ✓' : busy === 'location' ? 'Requesting…' : 'Allow location'}
        </button>
      </div>
    </div>
  );
}
