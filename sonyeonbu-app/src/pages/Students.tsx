import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { signedUrls, supabase, type Student } from '../supabase';
import Avatar from '../components/Avatar';
import { telHref } from '../utils';

export default function Students() {
  const [students, setStudents] = useState<Student[]>([]);
  const [photos, setPhotos] = useState<Record<string, string>>({});
  const [q, setQ] = useState('');
  const [cls, setCls] = useState('전체');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.from('students').select('*').order('class_name').order('name');
      const list = (data as Student[]) ?? [];
      setStudents(list);
      setLoading(false);
      setPhotos(await signedUrls('student-photos', list.map((s) => s.photo_path ?? '')));
    })();
  }, []);

  const classes = useMemo(
    () => ['전체', ...[...new Set(students.map((s) => s.class_name || '반 미정'))].sort()],
    [students],
  );

  const filtered = students.filter((s) => {
    const c = s.class_name || '반 미정';
    if (cls !== '전체' && c !== cls) return false;
    if (!q) return true;
    const hay = [s.name, s.guardian_name, s.school, s.guardian_phone, s.student_phone].join(' ');
    return hay.includes(q.trim());
  });

  return (
    <section>
      <div className="page-head">
        <h2>요람 <span className="count">{students.length}명</span></h2>
        <Link to="/students/new" className="btn primary">+ 등록</Link>
      </div>
      <input className="search" placeholder="이름, 학교, 보호자, 전화번호 검색" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="chips">
        {classes.map((c) => (
          <button key={c} className={'chip' + (c === cls ? ' active' : '')} onClick={() => setCls(c)}>{c}</button>
        ))}
      </div>

      {loading ? (
        <p className="muted">불러오는 중…</p>
      ) : filtered.length === 0 ? (
        <p className="empty">{students.length === 0 ? '아직 등록된 아이가 없습니다. "+ 등록"을 눌러 추가하세요.' : '검색 결과가 없습니다.'}</p>
      ) : (
        <ul className="list">
          {filtered.map((s) => (
            <li key={s.id} className="list-item">
              <Link to={`/students/${s.id}`} className="list-main">
                <Avatar url={s.photo_path ? photos[s.photo_path] : undefined} name={s.name} />
                <div>
                  <div className="strong">
                    {s.name} {!s.consent_info && <span className="badge warn" title="개인정보 동의서 미수령">동의서 미수령</span>}
                  </div>
                  <div className="muted small">
                    {[s.class_name, s.school, s.guardian_name && `보호자 ${s.guardian_name}`].filter(Boolean).join(' · ')}
                  </div>
                </div>
              </Link>
              {s.guardian_phone && (
                <a className="icon-btn" href={telHref(s.guardian_phone)} aria-label={`${s.name} 보호자에게 전화`}>📞</a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
