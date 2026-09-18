'use client';
import { useEffect, useMemo, useState } from 'react';
import { AuthProvider, useAuth } from '@/lib/auth';
import LoginForm from '@/components/LoginForm';
import RegisterForm from '@/components/RegisterForm';
import ConsentGate from '@/components/ConsentGate';
import CheckinFlow from '@/components/CheckinFlow';

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

function Screen() {
  const { user, loading, logout } = useAuth();
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [consented, setConsented] = useState(false);
  if (loading) return <div className="loading-state"><span className="spinner" /><p>Preparing your secure workspace…</p></div>;
  if (!user) return <div className="auth-shell"><BrandPanel /><section className="auth-panel"><div className="mobile-brand"><span className="mini-mark">S</span><strong>SAIV</strong></div><div className="auth-card">{authMode === 'login' ? <LoginForm onSwitchToRegister={() => setAuthMode('register')} /> : <RegisterForm onSwitchToLogin={() => setAuthMode('login')} />}</div><p className="auth-footer">Protected by secure identity verification</p></section></div>;
  const hasConsent = user.camera_consent && user.geolocation_consent;
  return <div className="app-shell">
    <header className="app-header"><div className="app-brand"><span className="mini-mark">S</span><div><strong>SAIV</strong><small>Student portal</small></div></div><div className="user-actions"><div className="user-avatar">{user.full_name?.charAt(0).toUpperCase() || 'S'}</div><div className="user-copy"><span>Welcome back</span><strong>{user.full_name}</strong></div><button onClick={logout} className="sign-out">Sign out</button></div></header>
    <main className="dashboard-main"><div className="dashboard-heading"><p className="eyebrow">Secure attendance</p><h1>{!hasConsent && !consented ? 'Set up verification' : 'Ready to check in?'}</h1><p>{!hasConsent && !consented ? 'Enable the required permissions once to continue.' : 'Choose your active session and complete a quick identity check.'}</p></div><div className="workflow-card">{!hasConsent && !consented ? <ConsentGate onContinue={() => setConsented(true)} /> : <CheckinFlow />}</div></main>
  </div>;
}

export default function Home() {
  useEffect(() => { if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {}); }, []);
  return <AuthProvider><Screen /></AuthProvider>;
}
