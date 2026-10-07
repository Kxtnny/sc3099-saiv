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
  venue_name?: string;
  qr_code_enabled?: boolean;
}

export default function SessionPicker({ onSelect }: { onSelect: (session: SessionSummary) => void }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<SessionSummary[]>('/sessions/active')
      .then((res) => setSessions(res.data))
      .catch(() => setError('Could not load active sessions.'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-sm text-gray-500">Loading active sessions…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (sessions.length === 0) {
    return <p className="text-sm text-gray-500">No sessions are open for check-in right now.</p>;
  }

  return (
    <div className="space-y-2 max-w-md">
      {sessions.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s)}
          className="w-full text-left rounded-lg border border-gray-200 p-4 hover:border-blue-400 hover:bg-blue-50 transition"
        >
          <p className="font-medium">{s.name}</p>
          <p className="text-sm text-gray-500">
            {s.course_code ? `${s.course_code} · ` : ''}
            {s.venue_name ?? 'Venue TBD'}
          </p>
        </button>
      ))}
    </div>
  );
}
