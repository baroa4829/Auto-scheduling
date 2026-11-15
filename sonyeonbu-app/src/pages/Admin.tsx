import { useEffect, useState } from 'react';
import { useAuth } from '../auth';
import { ROLE_LABEL, supabase, type Profile, type Role } from '../supabase';
import { errorMessage, formatDate, telHref } from '../utils';

const ROLES: Role[] = ['pending', 'member', 'teacher', 'admin'];

export default function Admin() {
  const { profile: me } = useAuth();
  const [users, setUsers] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    const { data } = await supabase.from('profiles').select('*').order('created_at', { ascending: false });
    setUsers((data as Profile[]) ?? []);
    setLoading(false);
  }
  useEffect(() => { load(); }, []);

  async function setRole(u: Profile, role: Role) {
    if (role === 'admin' && !confirm(`${u.name}님을 관리자로 지정할까요? 회원 승인/권한 변경이 가능해집니다.`)) return;
    const { error } = await supabase.from('profiles').update({ role }).eq('id', u.id);
    if (error) alert(errorMessage(error));
    load();
  }

  async function reject(u: Profile) {
    if (!confirm(`${u.name}님의 회원 정보를 삭제할까요?`)) return;
    const { error } = await supabase.from('profiles').delete().eq('id', u.id);
    if (error) alert(errorMessage(error));
    load();
  }

  const pending = users.filter((u) => u.role === 'pending');
  const others = users.filter((u) => u.role !== 'pending');

  const row = (u: Profile) => (
    <li key={u.id} className="list-item">
      <div className="list-main">
        <div>
          <div className="strong">{u.name || '(이름 없음)'} {u.id === me?.id && <span className="badge">나</span>}</div>
          <div className="muted small">
            {u.phone && <a href={telHref(u.phone)}>{u.phone}</a>} {u.phone && '· '}가입 {formatDate(u.created_at)}
          </div>
        </div>
      </div>
      {u.role === 'pending' ? (
        <div className="row gap">
          <button className="btn small primary" onClick={() => setRole(u, 'member')}>구성원 승인</button>
          <button className="btn small" onClick={() => setRole(u, 'teacher')}>교사 승인</button>
          <button className="btn small ghost" onClick={() => reject(u)}>거절</button>
        </div>
      ) : (
        <select value={u.role} disabled={u.id === me?.id} onChange={(e) => setRole(u, e.target.value as Role)}>
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
      )}
    </li>
  );

  if (loading) return <p className="muted">불러오는 중…</p>;

  return (
    <section>
      <h2>회원 관리</h2>
      <div className="card hint small">
        <b>구성원</b>: 앨범·영상 조회 · <b>교사</b>: + 요람 조회/수정, 사진·영상 등록 · <b>관리자</b>: + 회원 승인
      </div>
      <h3>승인 대기 <span className="count">{pending.length}</span></h3>
      {pending.length ? <ul className="list">{pending.map(row)}</ul> : <p className="empty small">대기 중인 신청이 없습니다.</p>}
      <h3>회원 <span className="count">{others.length}</span></h3>
      <ul className="list">{others.map(row)}</ul>
    </section>
  );
}
