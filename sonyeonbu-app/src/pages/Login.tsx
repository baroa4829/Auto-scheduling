import { useState, type FormEvent } from 'react';
import { supabase } from '../supabase';
import { errorMessage } from '../utils';

type Mode = 'login' | 'signup' | 'forgot';

export default function Login() {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      if (mode === 'login') {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else if (mode === 'signup') {
        if (!agree) throw new Error('개인정보 수집·이용에 동의해 주세요.');
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { name: name.trim(), phone: phone.trim() }, emailRedirectTo: window.location.origin },
        });
        if (error) throw error;
        if (!data.session) setNotice('가입 확인 메일을 보냈습니다. 메일의 링크를 누른 뒤 로그인해 주세요.');
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: window.location.origin + '/reset',
        });
        if (error) throw error;
        setNotice('비밀번호 재설정 메일을 보냈습니다.');
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen">
      <form className="card narrow" onSubmit={submit}>
        <div className="login-head">
          <img src="/icon.svg" alt="" width={56} height={56} />
          <h1>동석교회 소년부</h1>
          <p className="muted">
            {mode === 'login' ? '로그인' : mode === 'signup' ? '회원가입' : '비밀번호 찾기'}
          </p>
        </div>

        {mode === 'signup' && (
          <>
            <label>
              이름 <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="홍길동 (OO 어머니)" />
            </label>
            <label>
              연락처 <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="010-0000-0000" />
            </label>
          </>
        )}
        <label>
          이메일 <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        {mode !== 'forgot' && (
          <label>
            비밀번호
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>
        )}
        {mode === 'signup' && (
          <label className="check">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>
              회원 관리를 위해 이름·연락처·이메일을 수집하는 것에 동의합니다. (탈퇴 시 즉시 삭제)
            </span>
          </label>
        )}

        {error && <p className="error">{error}</p>}
        {notice && <p className="notice">{notice}</p>}

        <button className="btn primary block" disabled={busy}>
          {busy ? '처리 중…' : mode === 'login' ? '로그인' : mode === 'signup' ? '가입 신청' : '재설정 메일 보내기'}
        </button>

        <div className="login-links">
          {mode !== 'login' && <button type="button" className="link" onClick={() => setMode('login')}>로그인</button>}
          {mode !== 'signup' && <button type="button" className="link" onClick={() => setMode('signup')}>회원가입</button>}
          {mode !== 'forgot' && <button type="button" className="link" onClick={() => setMode('forgot')}>비밀번호 찾기</button>}
        </div>
        {mode === 'signup' && <p className="muted small">가입 후 관리자 승인이 있어야 이용할 수 있습니다.</p>}
      </form>
    </div>
  );
}
