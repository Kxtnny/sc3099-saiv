'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export interface SessionSummary {
  id: string;
  course_id: string;
  course_code?: string;
  name: string;
  status: string;
  scheduled_start: string;
  scheduled_end: string;
  checkin_opens_at: string;
  checkin_closes_at: string;
  venue_name?: string;
  qr_code_enabled?: boolean;
}

interface MyCheckInRef {
  session_id: string;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export default function SessionPicker({ onSelect }: { onSelect: (session: SessionSummary) => void }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  // Open sessions hidden because the student already has a check-in for them.
  const [alreadyDone, setAlreadyDone] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // /sessions/active lists every open session, including other courses'.
    // /sessions/my-sessions only returns courses the student is enrolled in.
    Promise.all([
      api.get<SessionSummary[]>('/sessions/my-sessions', { params: { status: 'active' } }),
      api.get<MyCheckInRef[]>('/checkins/my-checkins', { params: { limit: 100 } }),
    ])
      .then(([sessionsRes, checkinsRes]) => {
        const now = Date.now();
        // my-sessions does not filter by time, so drop windows that have closed.
        const open = sessionsRes.data.filter((s) => new Date(s.checkin_closes_at).getTime() > now);
        // The backend accepts one check-in per session, whatever its outcome,
        // so a session the student has already attempted moves to My check-ins.
        const done = new Set(checkinsRes.data.map((c) => c.session_id));
        const remaining = open
          .filter((s) => !done.has(s.id))
          .sort((a, b) => a.checkin_opens_at.localeCompare(b.checkin_opens_at));
        setSessions(remaining);
        setAlreadyDone(open.length - remaining.length);
      })
      .catch(() => setError('Could not load your sessions.'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-sm text-gray-500">Loading active sessions…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (sessions.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        {alreadyDone > 0
          ? 'You have already checked in to every open session. See My check-ins for the results.'
          : 'No sessions are open for check-in right now.'}
      </p>
    );
  }

  return (
    <div className="space-y-2 max-w-md">
      {sessions.map((s) => {
        const notOpenYet = new Date(s.checkin_opens_at).getTime() > Date.now();
        return (
          <button
            key={s.id}
            onClick={() => onSelect(s)}
            disabled={notOpenYet}
            className="w-full text-left rounded-lg border border-gray-200 p-4 hover:border-blue-400 hover:bg-blue-50 transition disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-gray-200 disabled:hover:bg-transparent"
          >
            <p className="font-medium">{s.name}</p>
            <p className="text-sm text-gray-500">
              {s.course_code ? `${s.course_code} · ` : ''}
              {s.venue_name ?? 'Venue TBD'}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              {notOpenYet
                ? `Check-in opens at ${formatTime(s.checkin_opens_at)}`
                : `Check-in closes at ${formatTime(s.checkin_closes_at)}`}
            </p>
          </button>
        );
      })}
    </div>
  );
}
