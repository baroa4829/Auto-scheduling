import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useRole } from '../auth';
import { signedUrls, supabase, type Album, type Photo } from '../supabase';
import { errorMessage, formatDate, resizeImage } from '../utils';

export default function AlbumDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { isTeacher } = useRole();
  const [album, setAlbum] = useState<Album | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<string>('');
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(async () => {
    const [{ data: a }, { data: p }] = await Promise.all([
      supabase.from('albums').select('*').eq('id', id!).maybeSingle(),
      supabase.from('photos').select('*').eq('album_id', id!).order('created_at'),
    ]);
    const list = (p as Photo[]) ?? [];
    setAlbum(a as Album | null);
    setPhotos(list);
    setLoading(false);
    setUrls(await signedUrls('album', list.map((x) => x.thumb_path)));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // 원본은 크게 볼 때만 URL 발급
  useEffect(() => {
    if (open === null) return;
    const targets = [photos[open], photos[open + 1], photos[open - 1]].filter(Boolean).map((p) => p.path).filter((p) => !urls[p]);
    if (targets.length) signedUrls('album', targets).then((m) => setUrls((u) => ({ ...u, ...m })));
  }, [open, photos, urls]);

  useEffect(() => {
    if (open === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(null);
      if (e.key === 'ArrowRight') setOpen((i) => (i !== null && i < photos.length - 1 ? i + 1 : i));
      if (e.key === 'ArrowLeft') setOpen((i) => (i !== null && i > 0 ? i - 1 : i));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, photos.length]);

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = [...(e.target.files ?? [])];
    e.target.value = '';
    let failed = 0;
    for (let i = 0; i < files.length; i++) {
      setProgress(`업로드 중 ${i + 1} / ${files.length}`);
      try {
        const base = `${id}/${crypto.randomUUID()}`;
        const [full, thumb] = await Promise.all([resizeImage(files[i], 1920, 0.85), resizeImage(files[i], 480, 0.75)]);
        const store = supabase.storage.from('album');
        const r1 = await store.upload(`${base}.jpg`, full, { contentType: 'image/jpeg' });
        if (r1.error) throw r1.error;
        const r2 = await store.upload(`${base}_t.jpg`, thumb, { contentType: 'image/jpeg' });
        if (r2.error) throw r2.error;
        const r3 = await supabase.from('photos').insert({ album_id: id, path: `${base}.jpg`, thumb_path: `${base}_t.jpg` });
        if (r3.error) throw r3.error;
      } catch (err) {
        failed++;
        console.error(err);
      }
    }
    setProgress(failed ? `${files.length - failed}장 완료, ${failed}장 실패` : '');
    load();
  }

  async function removePhoto(p: Photo) {
    if (!confirm('이 사진을 삭제할까요?')) return;
    await supabase.storage.from('album').remove([p.path, p.thumb_path]);
    const { error } = await supabase.from('photos').delete().eq('id', p.id);
    if (error) return alert(errorMessage(error));
    setOpen(null);
    load();
  }

  async function removeAlbum() {
    if (!album || !confirm(`"${album.title}" 앨범과 사진 ${photos.length}장을 모두 삭제할까요?`)) return;
    const paths = photos.flatMap((p) => [p.path, p.thumb_path]);
    for (let i = 0; i < paths.length; i += 100) await supabase.storage.from('album').remove(paths.slice(i, i + 100));
    const { error } = await supabase.from('albums').delete().eq('id', album.id);
    if (error) alert(errorMessage(error));
    else nav('/albums', { replace: true });
  }

  if (loading) return <p className="muted">불러오는 중…</p>;
  if (!album) return <p className="empty">앨범을 찾을 수 없습니다. <Link to="/albums">목록으로</Link></p>;

  const current = open !== null ? photos[open] : null;

  return (
    <section>
      <Link to="/albums" className="back">← 앨범</Link>
      <div className="page-head">
        <div>
          <h2>{album.title}</h2>
          <div className="muted small">{formatDate(album.event_date)} · {photos.length}장</div>
        </div>
        {isTeacher && (
          <label className="btn primary">
            + 사진
            <input type="file" accept="image/*" multiple hidden onChange={upload} disabled={!!progress && progress.startsWith('업로드')} />
          </label>
        )}
      </div>
      {progress && <p className="notice">{progress}</p>}

      {photos.length === 0 ? (
        <p className="empty">사진이 없습니다.</p>
      ) : (
        <div className="photo-grid">
          {photos.map((p, i) => (
            <button key={p.id} className="photo-cell" onClick={() => setOpen(i)}>
              {urls[p.thumb_path] ? <img src={urls[p.thumb_path]} alt="" loading="lazy" /> : <span />}
            </button>
          ))}
        </div>
      )}

      {isTeacher && <button className="btn danger ghost block mt" onClick={removeAlbum}>앨범 삭제</button>}

      {current && (
        <div className="lightbox" onClick={() => setOpen(null)}>
          <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
            <span>{open! + 1} / {photos.length}</span>
            <span className="row gap">
              {urls[current.path] && <a className="btn small" href={urls[current.path]} download target="_blank" rel="noreferrer">저장</a>}
              {isTeacher && <button className="btn small danger" onClick={() => removePhoto(current)}>삭제</button>}
              <button className="btn small" onClick={() => setOpen(null)}>닫기 ✕</button>
            </span>
          </div>
          <img src={urls[current.path] || urls[current.thumb_path]} alt="" onClick={(e) => e.stopPropagation()} />
          {open! > 0 && <button className="nav prev" onClick={(e) => { e.stopPropagation(); setOpen(open! - 1); }}>‹</button>}
          {open! < photos.length - 1 && <button className="nav next" onClick={(e) => { e.stopPropagation(); setOpen(open! + 1); }}>›</button>}
        </div>
      )}
    </section>
  );
}
