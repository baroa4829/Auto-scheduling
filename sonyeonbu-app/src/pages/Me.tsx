import { useState, type FormEvent } from 'react';
import { useAuth } from '../auth';
import { ROLE_LABEL, supabase } from '../supabase';
import { errorMessage } from '../utils';

export default function Me() {
  const { session, profile, refresh, signOut } = useAuth();
  const [name, setName] = useState(profile?.name ?? '');
  const [phone, setPhone] = useState(profile?.phone ?? '');
  const [msg, setMsg] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    const { error } = await supabase.from('profiles').update({ name: name.trim(), phone: phone.trim() || null }).eq('id', profile!.id);
    setMsg(error ? errorMessage(error) : '저장되었습니다.');
    refresh();
  }

  return (
    <section>
      <h2>내 정보</h2>
      <form className="card form" onSubmit={save}>
        <div className="muted small">{session?.user.email} · <span className="badge">{ROLE_LABEL[profile!.role]}</span></div>
        <label>이름<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label>연락처<input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" /></label>
        {msg && <p className="notice">{msg}</p>}
        <button className="btn primary block">저장</button>
      </form>
      <div className="card hint small">
        <b>홈 화면에 앱처럼 설치하기</b>
        <br />아이폰: Safari 공유 버튼 → "홈 화면에 추가"
        <br />안드로이드: Chrome 메뉴(⋮) → "홈 화면에 추가" 또는 "앱 설치"
      </div>
      <button className="btn ghost block" onClick={signOut}>로그아웃</button>
    </section>
  );
}
