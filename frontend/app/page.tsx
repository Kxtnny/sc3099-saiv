'use client';
import { useEffect, useMemo, useState } from 'react';
import { AuthProvider, useAuth } from '@/lib/auth';
import LoginForm from '@/components/LoginForm';
import RegisterForm from '@/components/RegisterForm';
import ConsentGate from '@/components/ConsentGate';
import CheckinFlow from '@/components/CheckinFlow';
import PrivacySettings from '@/components/PrivacySettings';
import FaceEnrollment from '@/components/FaceEnrollment';
import MyCheckins from '@/components/MyCheckins';
import { DASHBOARD_URL } from '@/lib/config';

const DAILY_QUOTES = [
  'Presence is the first step towards progress.',
  'Small moments of discipline build remarkable futures.',
  'Show up with purpose. Leave with progress.',
  'Learning begins the moment you arrive.',
  'Consistency turns ordinary days into extraordinary results.',
  'Every class is another chance to move forward.',
  'Your future is shaped by what you choose today.',
];

function DailyQuote() {
  const quote = useMemo(() => {
    const now = new Date();
    const day = Math.floor(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / 86400000);
    return DAILY_QUOTES[day % DAILY_QUOTES.length];
  }, []);
  return <p className="daily-quote">“{quote}”</p>;
}

function BrandPanel() {
  return <section className="brand-panel">
    <div className="brand-glow brand-glow-one" /><div className="brand-glow brand-glow-two" />
    <div className="brand-content">
      <div className="brand-mark"><span>S</span></div>
      <div className="brand-copy"><p className="eyebrow">Secure attendance · verified identity</p><h1>Presence,<br /><span>proven.</span></h1><p className="brand-description">A smarter, safer way to verify attendance—built around your identity, location and privacy.</p></div>
      <DailyQuote />
      <div className="trust-row"><span><i className="status-dot" /> Encrypted</span><span>Privacy-first</span><span>Real-time</span></div>
    </div>
  </section>;
}

type View = 'checkin' | 'history' | 'privacy' | 'enroll';

function StaffPanel() {
  return <div className="max-w-md space-y-3">
    <p className="text-sm text-gray-600">This portal is for students checking in. Instructors and TAs manage sessions, review flagged check-ins and view attendance in the staff dashboard.</p>
    <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer" className="inline-block rounded-md bg-blue-600 text-white text-sm px-4 py-2">Open the staff dashboard</a>
  </div>;
}

function Screen() {
  const { user, loading, logout } = useAuth();
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [view, setView] = useState<View>('checkin');
  // Set when a student skips first-time enrollment because the face service is down.
  const [enrollSkipped, setEnrollSkipped] = useState(false);
  if (loading) return <div className="loading-state"><span className="spinner" /><p>Preparing your secure workspace…</p></div>;
  if (!user) return <div className="auth-shell"><BrandPanel /><section className="auth-panel"><div className="mobile-brand"><span className="mini-mark">S</span><strong>SAIV</strong></div><div className="auth-card">{authMode === 'login' ? <LoginForm onSwitchToRegister={() => setAuthMode('register')} /> : <RegisterForm onSwitchToLogin={() => setAuthMode('login')} />}</div><p className="auth-footer">Protected by secure identity verification</p></section></div>;

  const isStudent = user.role === 'student';
  const hasConsent = !!(user.camera_consent && user.geolocation_consent);
  // After consent and before the first check-in, a student must enroll their face.
  const needsEnrollment = isStudent && hasConsent && !user.face_enrolled && !enrollSkipped;
  const current: View | 'consent' | 'enroll-first' | 'staff' =
    !isStudent ? 'staff'
    : view === 'privacy' || view === 'enroll' ? view
    : !hasConsent ? 'consent'
    : needsEnrollment ? 'enroll-first'
    : view;

  const heading: Record<typeof current, [string, string]> = {
    staff: ['Staff dashboard', 'Manage sessions and review check-ins in the dashboard.'],
    consent: ['Set up verification', 'Enable the required permissions once to continue.'],
    'enroll-first': ['Enroll your face', 'A one-time photo lets SAIV confirm it is you at check-in.'],
    enroll: [user.face_enrolled ? 'Re-enroll your face' : 'Enroll your face', 'Take a fresh photo to update your face template.'],
    checkin: ['Ready to check in?', 'Choose your active session and complete a quick identity check.'],
    history: ['My check-ins', 'Your attendance history across sessions.'],
    privacy: ['Privacy & permissions', 'Review or withdraw the consent you have given.'],
  };
  const [title, subtitle] = heading[current];
  const showTabs = isStudent && (current === 'checkin' || current === 'history');

  return <div className="app-shell">
    <header className="app-header"><div className="app-brand"><span className="mini-mark">S</span><div><strong>SAIV</strong><small>{isStudent ? 'Student portal' : 'Staff'}</small></div></div><div className="user-actions"><div className="user-avatar">{user.full_name?.charAt(0).toUpperCase() || 'S'}</div><div className="user-copy"><span>Welcome back</span><strong>{user.full_name}</strong></div>{isStudent && <button onClick={() => setView('privacy')} className="sign-out">Settings</button>}<button onClick={() => { setView('checkin'); logout(); }} className="sign-out">Sign out</button></div></header>
    <main className="dashboard-main"><div className="dashboard-heading"><p className="eyebrow">Secure attendance</p><h1>{title}</h1><p>{subtitle}</p></div>
      {showTabs && <div className="flex gap-2 mb-4" role="tablist">{(['checkin', 'history'] as const).map((v) => <button key={v} role="tab" aria-selected={current === v} onClick={() => setView(v)} className={`rounded-full border px-4 py-1.5 text-sm font-medium ${current === v ? 'bg-blue-600 border-blue-600 text-white' : 'border-gray-300 text-gray-700'}`}>{v === 'checkin' ? 'Check in' : 'My check-ins'}</button>)}</div>}
      <div className="workflow-card">
        {current === 'staff' && <StaffPanel />}
        {current === 'consent' && <ConsentGate />}
        {current === 'enroll-first' && <FaceEnrollment onDone={() => {}} onSkip={() => setEnrollSkipped(true)} />}
        {current === 'enroll' && <FaceEnrollment onDone={() => setView('privacy')} onCancel={() => setView('privacy')} />}
        {current === 'checkin' && <CheckinFlow />}
        {current === 'history' && <MyCheckins />}
        {current === 'privacy' && <PrivacySettings onBack={() => setView('checkin')} onReenroll={() => setView('enroll')} />}
      </div>
    </main>
  </div>;
}

export default function Home() {
  useEffect(() => { if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {}); }, []);
  return <AuthProvider><Screen /></AuthProvider>;
}
