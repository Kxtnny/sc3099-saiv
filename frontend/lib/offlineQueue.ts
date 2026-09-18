import localforage from 'localforage';
import { api } from './api';

const queueStore = localforage.createInstance({ name: 'saiv', storeName: 'checkin_queue' });

export interface QueuedCheckin {
  queueId: string;
  payload: {
    session_id: string;
    latitude: number;
    longitude: number;
    location_accuracy_meters?: number;
    device_fingerprint: string;
    liveness_challenge_response?: string;
  };
  queuedAt: string;
}

export async function enqueueCheckin(payload: QueuedCheckin['payload']): Promise<void> {
  const queueId = crypto.randomUUID();
  await queueStore.setItem(queueId, {
    queueId,
    payload,
    queuedAt: new Date().toISOString(),
  } satisfies QueuedCheckin);
}

export async function listQueuedCheckins(): Promise<QueuedCheckin[]> {
  const items: QueuedCheckin[] = [];
  await queueStore.iterate<QueuedCheckin, void>((value) => {
    items.push(value);
  });
  return items.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
}

/** Attempts to submit every queued check-in. Entries that succeed (or fail
 * with a definitive 4xx, e.g. "already checked in") are removed; entries
 * that fail because we're still offline are left for the next attempt. */
export async function syncQueuedCheckins(): Promise<{ synced: number; remaining: number }> {
  const items = await listQueuedCheckins();
  let synced = 0;

  for (const item of items) {
    try {
      await api.post('/checkins/', item.payload);
      await queueStore.removeItem(item.queueId);
      synced += 1;
    } catch (err: any) {
      const status = err?.response?.status;
      if (status && status < 500) {
        // Backend rejected it outright (e.g. duplicate, window closed) —
        // don't keep retrying forever.
        await queueStore.removeItem(item.queueId);
      }
      // else: likely offline / 5xx — leave it queued.
    }
  }

  const remaining = (await listQueuedCheckins()).length;
  return { synced, remaining };
}

export function watchConnectivity(onOnline: () => void): () => void {
  window.addEventListener('online', onOnline);
  return () => window.removeEventListener('online', onOnline);
}
