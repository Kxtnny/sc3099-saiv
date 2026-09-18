'use client';
import { useState } from 'react';
import { useAuth } from '@/lib/auth';

export default function LoginForm({ onSwitchToRegister }: { onSwitchToRegister: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false); const [error, setError] = useState<string | null>(null); const [submitting, setSubmitting] = useState(false);
  async function handleSubmit(e: React.FormEvent) { e.preventDefault(); setError(null); setSubmitting(true); try { await login(email, password); } catch (err: any) { const detail = err?.response?.data?.detail; setError(typeof detail === 'string' ? detail : 'Login failed. Check your email and password.'); } finally { setSubmitting(false); } }
  return <form onSubmit={handleSubmit}>
    <div className="form-heading"><p className="eyebrow">Student access</p><h2>Welcome back</h2><p>Sign in to securely verify your attendance.</p></div>
    <div className="field-group"><label htmlFor="login-email">Email address</label><div className="input-wrap"><span className="input-icon">@</span><input id="login-email" type="email" required autoComplete="email" placeholder="name@university.edu" value={email} onChange={(e) => setEmail(e.target.value)} /></div></div>
    <div className="field-group"><label htmlFor="login-password">Password</label><div className="input-wrap"><span className="input-icon key-icon">◆</span><input id="login-password" type={showPassword ? 'text' : 'password'} required autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} /><button type="button" className="reveal-button" onClick={() => setShowPassword(!showPassword)}>{showPassword ? 'Hide' : 'Show'}</button></div></div>
    {error && <div className="form-alert" role="alert">{error}</div>}
    <button type="submit" disabled={submitting} className="primary-button">{submitting ? <><span className="button-spinner" />Signing in…</> : <>Sign in securely <span>→</span></>}</button>
    <div className="form-divider"><span>New to SAIV?</span></div><button type="button" onClick={onSwitchToRegister} className="secondary-button">Create student account</button>
  </form>;
}
