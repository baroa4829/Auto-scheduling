import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { signedUrls, supabase, type Student } from '../supabase';
import Avatar from '../components/Avatar';
import { age, errorMessage, formatDate, telHref } from '../utils';

export default function StudentDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [s, setS] = useState<Student | null>(null);
  const [photo, setPhoto] = useState<string>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.from('students').select('*').eq('id', id!).maybeSingle();
      setS(data as Student | null);
      setLoading(false);
      if (data?.photo_path) setPhoto((await signedUrls('student-photos', [data.photo_path]))[data.photo_path]);
    })();
  }, [id]);

  async function remove() {
    if (!s || !confirm(`${s.name} 어린이의 정보를 완전히 삭제할까요?\n(졸업·전출 시 사용, 되돌릴 수 없습니다)`)) return;
    if (s.photo_path) await supabase.storage.from('student-photos').remove([s.photo_path]);
    const { error } = await supabase.from('students').delete().eq('id', s.id);
    if (error) alert(errorMessage(error));
    else nav('/students', { replace: true });
  }

  if (loading) return <p className="muted">불러오는 중…</p>;
  if (!s) return <p className="empty">정보를 찾을 수 없습니다. <Link to="/students">목록으로</Link></p>;

  const rows: [string, React.ReactNode][] = [
    ['반', s.class_name],
    ['성별', s.gender],
    ['생년월일', s.birth_date && `${formatDate(s.birth_date)} (${age(s.birth_date)})`],
    ['학교', s.school],
    ['본인 연락처', s.student_phone && <PhoneLinks phone={s.student_phone} />],
    ['보호자', [s.guardian_name, s.guardian_relation && `(${s.guardian_relation})`].filter(Boolean).join(' ')],
    ['보호자 연락처', s.guardian_phone && <PhoneLinks phone={s.guardian_phone} />],
    ['주소', s.address],
    ['메모', s.notes && <span className="pre">{s.notes}</span>],
  ];

  return (
    <section>
      <Link to="/students" className="back">← 요람</Link>
      <div className="card profile">
        <Avatar url={photo} name={s.name} size={112} />
        <h2>{s.name}</h2>
        <div className="row gap center wrap">
          <span className={'badge ' + (s.consent_info ? 'ok' : 'warn')}>개인정보 동의 {s.consent_info ? '완료' : '미수령'}</span>
          <span className={'badge ' + (s.consent_photo ? 'ok' : 'warn')}>사진 공개 {s.consent_photo ? '동의' : '비동의'}</span>
        </div>
      </div>
      <dl className="card details">
        {rows.filter(([, v]) => v).map(([k, v]) => (
          <div key={k} className="detail-row"><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <div className="row gap">
        <Link to={`/students/${s.id}/edit`} className="btn primary grow">수정</Link>
        <button className="btn danger" onClick={remove}>삭제</button>
      </div>
    </section>
  );
}

function PhoneLinks({ phone }: { phone: string }) {
  return (
    <span className="row gap">
      <a href={telHref(phone)}>{phone}</a>
      <a className="small" href={telHref(phone).replace('tel:', 'sms:')}>문자</a>
    </span>
  );
}
