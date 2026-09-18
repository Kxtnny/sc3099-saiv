import localforage from 'localforage';
import { api } from './api';

const deviceStore = localforage.createInstance({ name: 'saiv', storeName: 'device' });

const FINGERPRINT_KEY = 'device_fingerprint';
const KEYPAIR_KEY = 'device_keypair'; // CryptoKeyPair, structured-cloned into IndexedDB
const DEVICE_ID_KEY = 'registered_device_id';

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * A stable-per-browser-profile fingerprint: a random UUID generated once
 * and persisted in IndexedDB, combined with a few coarse, low-entropy
 * environment signals. This is NOT meant to survive reinstalls/incognito —
 * that's intentional, since the backend's device-trust model treats a new
 * fingerprint as "unknown device" and scores it accordingly.
 */
export async function getDeviceFingerprint(): Promise<string> {
  let fp = await deviceStore.getItem<string>(FINGERPRINT_KEY);
  if (fp) return fp;

  const seed = [
    crypto.randomUUID(),
    navigator.userAgent,
    navigator.language,
    String(screen.width),
    String(screen.height),
  ].join('|');

  fp = await sha256Hex(seed);
  await deviceStore.setItem(FINGERPRINT_KEY, fp);
  return fp;
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function toPem(base64: string): string {
  const lines = base64.match(/.{1,64}/g) ?? [base64];
  return `-----BEGIN PUBLIC KEY-----\n${lines.join('\n')}\n-----END PUBLIC KEY-----`;
}

/** Gets (or creates) this device's ECDSA P-256 key pair. The private key is
 * non-extractable — it never leaves the browser, even as bytes. */
async function getOrCreateKeyPair(): Promise<CryptoKeyPair> {
  const existing = await deviceStore.getItem<CryptoKeyPair>(KEYPAIR_KEY);
  if (existing?.privateKey && existing?.publicKey) return existing;

  const keyPair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    false, // non-extractable private key
    ['sign', 'verify']
  );
  await deviceStore.setItem(KEYPAIR_KEY, keyPair);
  return keyPair;
}

export async function getDevicePublicKeyPem(): Promise<string> {
  const { publicKey } = await getOrCreateKeyPair();
  const spki = await crypto.subtle.exportKey('spki', publicKey);
  return toPem(arrayBufferToBase64(spki));
}

/** Signs a payload with this device's private key (base64 signature),
 * for optional use with POST /device/attest. */
export async function signWithDeviceKey(payload: string): Promise<string> {
  const { privateKey } = await getOrCreateKeyPair();
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' },
    privateKey,
    new TextEncoder().encode(payload)
  );
  return arrayBufferToBase64(signature);
}

/** Registers this device with the backend once per browser profile. Safe
 * to call on every check-in — it no-ops after the first successful call. */
export async function ensureDeviceRegistered(): Promise<string> {
  const fingerprint = await getDeviceFingerprint();

  const cachedId = await deviceStore.getItem<string>(DEVICE_ID_KEY);
  if (cachedId) return fingerprint;

  const publicKeyPem = await getDevicePublicKeyPem();
  const platform = /Mobi|Android/i.test(navigator.userAgent) ? 'web' : 'web';

  try {
    const { data } = await api.post('/devices/register', {
      device_fingerprint: fingerprint,
      device_name: `${navigator.platform || 'Browser'} device`,
      platform,
      public_key: publicKeyPem,
    });
    await deviceStore.setItem(DEVICE_ID_KEY, data.id);
  } catch {
    // Registration is best-effort — checkins/ still accepts a fingerprint
    // for an unregistered device; it's just scored as lower trust.
  }

  return fingerprint;
}
