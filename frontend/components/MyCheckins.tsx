'use client';

import { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';

interface MyCheckIn {
  id: string;
  session_id: string;
  session_name?: string | null;
  course_code?: string | null;
  status: 'pending' | 'approved' | 'flagged' | 'rejected' | 'appealed' | string;
  checked_in_at: string;
  risk_score: number;
}

const STATUS_STYLE: Record<string, { label: string; className: string }> = {
  approved: { label: 'Approved', className: 'bg-green-50 text-green-800 border-green-300' },
  pending: { label: 'Pending review', className: 'bg-yellow-50 text-yellow-800 border-yellow-300' },
  flagged: { label: 'Under review', className: 'bg-yellow-50 text-yellow-800 border-yellow-300' },
  rejected: { label: 'Rejected', className: 'bg-red-50 text-red-800 border-red-300' },
  appealed: { label: 'Appeal under review', className: 'bg-blue-50 text-blue-800 border-blue-300' },
};

// Mirrors POST /checkins/{id}/appeal: rejected or flagged, within 7 days.
// The backend also refuses a second appeal; my-checkins does not say whether
// one was made, so that case is caught from the server's reply.
const APPEALABLE = new Set(['rejected', 'flagged']);
const APPEAL_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_REASON = 2000;

function canAppeal(c: MyCheckIn): boolean {
  return APPEALABLE.has(c.status) && Date.now() - new Date(c.checked_in_at).getTime() <= APPEAL_WINDOW_MS;
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function describeAppealError(err: unknown): string {
  if (isAxiosError(err)) {
    if (!err.response) return 'Could not reach the server. Check your connection and try again.';
    const detail = (err.response.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return 'Could not submit your appeal. Please try again.';
}

function AppealForm({
  checkIn,
  onAppealed,
  onBlocked,
  onCancel,
}: {
  checkIn: MyCheckIn;
  onAppealed: (status: string) => void;
  /** The server refused for a reason the student cannot fix (e.g. already appealed). */
  onBlocked: (message: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = reason.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<{ status: string }>(`/checkins/${checkIn.id}/appeal`, {
        appeal_reason: text,
      });
      onAppealed(data.status);
    } catch (err) {
      const message = describeAppealError(err);
      if (isAxiosError(err) && err.response?.status === 400) {
        onBlocked(message);
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 space-y-2">
      <label htmlFor={`appeal-${checkIn.id}`} className="block text-sm font-medium">
        Why should this check-in be accepted?
      </label>
      <textarea
        id={`appeal-${checkIn.id}`}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={MAX_REASON}
        rows={3}
        placeholder="e.g. I was in the lecture hall, but my phone's GPS placed me outside the building."
        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
      />
      <p className="text-xs text-gray-500">
        Your instructor will review it. You can only appeal a check-in once.
      </p>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || !reason.trim()}
          className="rounded-md bg-blue-600 text-white text-sm px-4 py-2 disabled:opacity-50"
        >
          {busy ? 'Submitting…' : 'Submit appeal'}
        </button>
        <button type="button" onClick={onCancel} disabled={busy} className="text-sm underline">
          Cancel
        </button>
      </div>
    </form>
  );
}

/** The student's own attendance history (GET /checkins/my-checkins). */
export default function MyCheckins() {
  const [items, setItems] = useState<MyCheckIn[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [appealingId, setAppealingId] = useState<string | null>(null);
  // Per check-in note after an appeal attempt (success, or why it was refused).
  const [notes, setNotes] = useState<Record<string, { text: string; blocked: boolean }>>({});

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    api
      .get<MyCheckIn[]>('/checkins/my-checkins', { params: { limit: 50 } })
      .then((res) => !cancelled && setItems(res.data))
      .catch(() => !cancelled && setError('Could not load your check-ins.'));
    return () => {
      cancelled = true;
    };
  }, [reload]);

  function markAppealed(id: string, status: string) {
    setItems((prev) => prev?.map((c) => (c.id === id ? { ...c, status } : c)) ?? prev);
    setNotes((prev) => ({ ...prev, [id]: { text: 'Appeal submitted. Your instructor will review it.', blocked: false } }));
    setAppealingId(null);
  }

  function markBlocked(id: string, message: string) {
    setNotes((prev) => ({ ...prev, [id]: { text: message, blocked: true } }));
    setAppealingId(null);
  }

  if (error) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-red-600">{error}</p>
        <button onClick={() => setReload((n) => n + 1)} className="text-sm underline">
          Try again
        </button>
      </div>
    );
  }
  if (!items) return <p className="text-sm text-gray-500">Loading your check-ins…</p>;
  if (items.length === 0) {
    return <p className="text-sm text-gray-500">You haven’t checked in to any sessions yet.</p>;
  }

  return (
    <ul className="space-y-2 max-w-xl">
      {items.map((c) => {
        const style = STATUS_STYLE[c.status] ?? {
          label: c.status,
          className: 'bg-gray-50 text-gray-700 border-gray-300',
        };
        const note = notes[c.id];
        const showAppeal = canAppeal(c) && !note?.blocked && appealingId !== c.id;
        return (
          <li key={c.id} className="rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium truncate">{c.session_name ?? 'Session'}</p>
                <p className="text-sm text-gray-500">
                  {c.course_code ? `${c.course_code} · ` : ''}
                  {formatWhen(c.checked_in_at)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {showAppeal && (
                  <button
                    onClick={() => setAppealingId(c.id)}
                    disabled={appealingId !== null}
                    className="text-sm underline text-blue-700 disabled:opacity-50"
                  >
                    Appeal
                  </button>
                )}
                <span className={`rounded-full border px-3 py-1 text-xs font-medium ${style.className}`}>
                  {style.label}
                </span>
              </div>
            </div>
            {note && (
              <p className={`mt-2 text-sm ${note.blocked ? 'text-gray-600' : 'text-blue-700'}`}>{note.text}</p>
            )}
            {appealingId === c.id && (
              <AppealForm
                checkIn={c}
                onAppealed={(status) => markAppealed(c.id, status)}
                onBlocked={(message) => markBlocked(c.id, message)}
                onCancel={() => setAppealingId(null)}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}
