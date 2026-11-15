import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { signedUrls, supabase, type Student } from '../supabase';
import Avatar from '../components/Avatar';
import { errorMessage, resizeImage } from '../utils';

type Form = Omit<Student, 'id' | 'photo_path'>;

const EMPTY: Form = {
  name: '', gender: null, birth_date: null, class_name: '', school: '', student_phone: '',
  guardian_name: '', guardian_relation: '', guardian_phone: '', address: '', notes: '',
  consent_info: false, consent_photo: false,
};

export default function StudentForm() {
  const { id } = useParams();
  const nav = useNavigate();
  const [form, setForm] = useState<Form>(EMPTY);
  const [photoPath, setPhotoPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<string>();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    (async () => {
      const { data } = await supabase.from('students').select('*').eq('id', id).maybeSingle();
      if (!data) return;
      const { id: _id, photo_path, ...rest } = data as Student;
      setForm({ ...EMPTY, ...rest });
      setPhotoPath(photo_path);
      if (photo_path) setPreview((await signedUrls('student-photos', [photo_path]))[photo_path]);
    })();
  }, [id]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const text = (k: keyof Form) => ({
    value: (form[k] as string | null) ?? '',
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(k, e.target.value as never),
  });

  function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      let newPath = photoPath;
      if (file) {
        const blob = await resizeImage(file, 800);
        newPath = `${crypto.randomUUID()}.jpg`;
        const { error } = await supabase.storage.from('student-photos').upload(newPath, blob, { contentType: 'image/jpeg' });
        if (error) throw error;
      }
      const payload = {
        ...form,
        name: form.name.trim(),
        birth_date: form.birth_date || null,
        gender: form.gender || null,
        photo_path: newPath,
      };
      const res = id
        ? await supabase.from('students').update(payload).eq('id', id).select('id').single()
        : await supabase.from('students').insert(payload).select('id').single();
      if (res.error) throw res.error;
      if (file && photoPath && photoPath !== newPath) await supabase.storage.from('student-photos').remove([photoPath]);
      nav(`/students/${res.data.id}`, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <section>
      <Link to={id ? `/students/${id}` : '/students'} className="back">← 취소</Link>
      <h2>{id ? '정보 수정' : '아이 등록'}</h2>
      <form className="card form" onSubmit={submit}>
        <label className="photo-pick">
          <Avatar url={preview} name={form.name} size={96} />
          <span className="btn small">사진 {preview ? '변경' : '선택'}</span>
          <input type="file" accept="image/*" onChange={pick} hidden />
        </label>

        <label>이름 *<input {...text('name')} required /></label>
        <div className="grid2">
          <label>성별
            <select value={form.gender ?? ''} onChange={(e) => set('gender', (e.target.value || null) as Form['gender'])}>
              <option value="">선택</option><option>남</option><option>여</option>
            </select>
          </label>
          <label>생년월일<input type="date" value={form.birth_date ?? ''} onChange={(e) => set('birth_date', e.target.value || null)} /></label>
        </div>
        <div className="grid2">
          <label>반<input {...text('class_name')} placeholder="예: 5학년 1반" /></label>
          <label>학교<input {...text('school')} placeholder="예: 동탄초" /></label>
        </div>
        <label>본인 연락처<input {...text('student_phone')} inputMode="tel" placeholder="010-0000-0000" /></label>
        <div className="grid2">
          <label>보호자 이름<input {...text('guardian_name')} /></label>
          <label>관계<input {...text('guardian_relation')} placeholder="모 / 부 / 조모" /></label>
        </div>
        <label>보호자 연락처<input {...text('guardian_phone')} inputMode="tel" placeholder="010-0000-0000" /></label>
        <label>주소<input {...text('address')} /></label>
        <label>메모 (알레르기, 기도제목 등)<textarea rows={3} {...text('notes')} /></label>

        <fieldset className="consent">
          <legend>보호자 동의</legend>
          <label className="check"><input type="checkbox" checked={form.consent_info} onChange={(e) => set('consent_info', e.target.checked)} /><span>개인정보 수집·이용 동의서를 받았습니다</span></label>
          <label className="check"><input type="checkbox" checked={form.consent_photo} onChange={(e) => set('consent_photo', e.target.checked)} /><span>앨범 사진 공개에 동의했습니다</span></label>
        </fieldset>

        {error && <p className="error">{error}</p>}
        <button className="btn primary block" disabled={busy}>{busy ? '저장 중…' : '저장'}</button>
      </form>
    </section>
  );
}
