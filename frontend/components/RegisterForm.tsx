'use client';
import { useMemo, useState } from 'react';
import { useAuth } from '@/lib/auth';

export default function RegisterForm({ onSwitchToLogin }: { onSwitchToLogin: () => void }) {
  const { register } = useAuth();
  const [fullName, setFullName] = useState(''); const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [confirmPassword, setConfirmPassword] = useState('');
  const [showPasswords, setShowPasswords] = useState(false); const [error, setError] = useState<string | null>(null); const [submitting, setSubmitting] = useState(false);
  const passwordsMatch = confirmPassword.length > 0 && password === confirmPassword;
  const strength = useMemo(() => Math.min(4, [password.length >= 8, /[A-Z]/.test(password), /[0-9]/.test(password), /[^A-Za-z0-9]/.test(password)].filter(Boolean).length), [password]);
  async function handleSubmit(e: React.FormEvent) { e.preventDefault(); setError(null); if (password !== confirmPassword) { setError('Your passwords do not match. Please check them and try again.'); return; } setSubmitting(true); try { await register(email, password, fullName); } catch (err: any) { const detail = err?.response?.data?.detail; setError(typeof detail === 'string' ? detail : 'Registration failed. Please try again.'); } finally { setSubmitting(false); } }
  return <form onSubmit={handleSubmit}>
    <div className="form-heading compact"><p className="eyebrow">Join the platform</p><h2>Create account</h2><p>Set up your secure student identity in seconds.</p></div>
    <div className="field-group"><label htmlFor="full-name">Full name</label><div className="input-wrap"><span className="input-icon">◇</span><input id="full-name" required autoComplete="name" placeholder="Your full name" value={fullName} onChange={(e) => setFullName(e.target.value)} /></div></div>
    <div className="field-group"><label htmlFor="register-email">Email address</label><div className="input-wrap"><span className="input-icon">@</span><input id="register-email" type="email" required autoComplete="email" placeholder="name@university.edu" value={email} onChange={(e) => setEmail(e.target.value)} /></div></div>
    <div className="field-grid"><div className="field-group"><label htmlFor="register-password">Password</label><div className="input-wrap"><span className="input-icon key-icon">◆</span><input id="register-password" type={showPasswords ? 'text' : 'password'} required minLength={8} autoComplete="new-password" placeholder="Minimum 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} /></div></div><div className="field-group"><label htmlFor="confirm-password">Confirm password</label><div className={`input-wrap ${confirmPassword ? (passwordsMatch ? 'valid' : 'invalid') : ''}`}><span className="input-icon key-icon">◆</span><input id="confirm-password" type={showPasswords ? 'text' : 'password'} required minLength={8} autoComplete="new-password" placeholder="Repeat password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /><span className="match-indicator">{confirmPassword ? (passwordsMatch ? '✓' : '!') : ''}</span></div></div></div>
    <div className="password-meta"><div className="strength-bars">{[1,2,3,4].map((level) => <i key={level} className={strength >= level ? 'active' : ''} />)}</div><span>{password.length < 8 ? 'Use at least 8 characters' : strength >= 3 ? 'Strong password' : 'Add a number or symbol'}</span><button type="button" onClick={() => setShowPasswords(!showPasswords)}>{showPasswords ? 'Hide' : 'Show'} passwords</button></div>
    {error && <div className="form-alert" role="alert">{error}</div>}
    <button type="submit" disabled={submitting || !passwordsMatch} className="primary-button">{submitting ? <><span className="button-spinner" />Creating account…</> : <>Create secure account <span>→</span></>}</button>
    <p className="switch-copy">Already registered? <button type="button" onClick={onSwitchToLogin}>Sign in</button></p>
  </form>;
}
