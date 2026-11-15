import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../supabase';
import { errorMessage } from '../utils';

export default function ResetPassword() {
  const nav = useNavigate();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const { error } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (error) setError(errorMessage(error));
    else nav('/', { replace: true });
  }

  return (
    <div className="center-screen">
      <form className="card narrow" onSubmit={submit}>
        <h1>새 비밀번호 설정</h1>
        <label>
          새 비밀번호
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={6} required autoComplete="new-password" />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn primary block" disabled={busy}>변경하기</button>
      </form>
    </div>
  );
}
