'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface MyCheckIn {
  id: string;
  session_id: string;
  session_name?: string | null;
  course_code?: string | null;
  status: 'pending' | 'approved' | 'flagged' | 'rejected' | string;
  checked_in_at: string;
  risk_score: number;
}

const STATUS_STYLE: Record<string, { label: string; className: string }> = {
  approved: { label: 'Approved', className: 'bg-green-50 text-green-800 border-green-300' },
  pending: { label: 'Pending review', className: 'bg-yellow-50 text-yellow-800 border-yellow-300' },
  flagged: { label: 'Under review', className: 'bg-yellow-50 text-yellow-800 border-yellow-300' },
  rejected: { label: 'Rejected', className: 'bg-red-50 text-red-800 border-red-300' },
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** The student's own attendance history (GET /checkins/my-checkins). */
export default function MyCheckins() {
  const [items, setItems] = useState<MyCheckIn[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

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
        return (
          <li
            key={c.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 p-4"
          >
            <div className="min-w-0">
              <p className="font-medium truncate">{c.session_name ?? 'Session'}</p>
              <p className="text-sm text-gray-500">
                {c.course_code ? `${c.course_code} · ` : ''}
                {formatWhen(c.checked_in_at)}
              </p>
            </div>
            <span className={`shrink-0 rounded-full border px-3 py-1 text-xs font-medium ${style.className}`}>
              {style.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
