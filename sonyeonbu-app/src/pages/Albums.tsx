import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useRole } from '../auth';
import { signedUrls, supabase, type Album } from '../supabase';
import { errorMessage, formatDate } from '../utils';

interface AlbumCard extends Album { cover?: string; count: number }

export default function Albums() {
  const { isTeacher } = useRole();
  const nav = useNavigate();
  const [albums, setAlbums] = useState<AlbumCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      const [{ data: a }, { data: p }] = await Promise.all([
        supabase.from('albums').select('*').order('event_date', { ascending: false, nullsFirst: false }).order('created_at', { ascending: false }),
        supabase.from('photos').select('album_id, thumb_path').order('created_at'),
      ]);
      const photos = (p as { album_id: string; thumb_path: string }[]) ?? [];
      const first: Record<string, string> = {};
      const count: Record<string, number> = {};
      for (const ph of photos) {
        first[ph.album_id] ??= ph.thumb_path;
        count[ph.album_id] = (count[ph.album_id] ?? 0) + 1;
      }
      const urls = await signedUrls('album', Object.values(first));
      setAlbums(((a as Album[]) ?? []).map((al) => ({ ...al, cover: urls[first[al.id]], count: count[al.id] ?? 0 })));
      setLoading(false);
    })();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError('');
    const { data, error } = await supabase.from('albums').insert({ title: title.trim(), event_date: date || null }).select('id').single();
    if (error) setError(errorMessage(error));
    else nav(`/albums/${data.id}`);
  }

  return (
    <section>
      <div className="page-head">
        <h2>앨범</h2>
        {isTeacher && !creating && <button className="btn primary" onClick={() => setCreating(true)}>+ 새 앨범</button>}
      </div>
      {creating && (
        <form className="card form" onSubmit={create}>
          <label>앨범 이름<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 2026 여름성경학교" required autoFocus /></label>
          <label>날짜<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
          {error && <p className="error">{error}</p>}
          <div className="row gap">
            <button className="btn primary grow">만들기</button>
            <button type="button" className="btn ghost" onClick={() => setCreating(false)}>취소</button>
          </div>
        </form>
      )}
      {loading ? (
        <p className="muted">불러오는 중…</p>
      ) : albums.length === 0 ? (
        <p className="empty">아직 앨범이 없습니다.</p>
      ) : (
        <div className="album-grid">
          {albums.map((a) => (
            <Link key={a.id} to={`/albums/${a.id}`} className="album-card">
              <div className="album-cover">{a.cover ? <img src={a.cover} alt="" loading="lazy" /> : <span>🖼️</span>}</div>
              <div className="album-meta">
                <div className="strong ellipsis">{a.title}</div>
                <div className="muted small">{formatDate(a.event_date)} · {a.count}장</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
