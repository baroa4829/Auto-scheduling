import { useEffect, useState, type FormEvent } from 'react';
import { useRole } from '../auth';
import { supabase, type Video } from '../supabase';
import { errorMessage, formatDate, parseYouTubeId } from '../utils';

export default function Videos() {
  const { isTeacher } = useRole();
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [link, setLink] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState('');
  const [playing, setPlaying] = useState<string | null>(null);

  async function load() {
    const { data } = await supabase.from('videos').select('*').order('event_date', { ascending: false, nullsFirst: false }).order('created_at', { ascending: false });
    setVideos((data as Video[]) ?? []);
    setLoading(false);
  }
  useEffect(() => { load(); }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError('');
    const youtube_id = parseYouTubeId(link);
    if (!youtube_id) return setError('유튜브 주소를 확인해 주세요. (예: https://youtu.be/xxxx)');
    const { error } = await supabase.from('videos').insert({ title: title.trim(), youtube_id, event_date: date || null });
    if (error) return setError(errorMessage(error));
    setTitle(''); setLink(''); setAdding(false);
    load();
  }

  async function remove(v: Video) {
    if (!confirm(`"${v.title}" 영상을 목록에서 삭제할까요?\n(유튜브에 올라간 영상 자체는 삭제되지 않습니다)`)) return;
    const { error } = await supabase.from('videos').delete().eq('id', v.id);
    if (error) alert(errorMessage(error));
    else load();
  }

  return (
    <section>
      <div className="page-head">
        <h2>영상</h2>
        {isTeacher && !adding && <button className="btn primary" onClick={() => setAdding(true)}>+ 영상 추가</button>}
      </div>
      {adding && (
        <form className="card form" onSubmit={add}>
          <label>제목<input value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="예: 성탄절 율동 발표" /></label>
          <label>유튜브 주소<input value={link} onChange={(e) => setLink(e.target.value)} required placeholder="https://youtu.be/..." inputMode="url" /></label>
          <p className="muted small">유튜브에 <b>'일부 공개'</b>로 올린 뒤 공유 링크를 붙여넣으세요. 앱 밖에서는 검색되지 않습니다.</p>
          <label>날짜<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
          {error && <p className="error">{error}</p>}
          <div className="row gap">
            <button className="btn primary grow">추가</button>
            <button type="button" className="btn ghost" onClick={() => setAdding(false)}>취소</button>
          </div>
        </form>
      )}
      {loading ? (
        <p className="muted">불러오는 중…</p>
      ) : videos.length === 0 ? (
        <p className="empty">아직 영상이 없습니다.</p>
      ) : (
        <div className="video-list">
          {videos.map((v) => (
            <article key={v.id} className="card video-card">
              <div className="video-frame">
                {playing === v.id ? (
                  <iframe
                    src={`https://www.youtube-nocookie.com/embed/${v.youtube_id}?autoplay=1&rel=0`}
                    title={v.title}
                    allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                    allowFullScreen
                  />
                ) : (
                  <button className="video-thumb" onClick={() => setPlaying(v.id)} aria-label={`${v.title} 재생`}>
                    <img src={`https://i.ytimg.com/vi/${v.youtube_id}/hqdefault.jpg`} alt="" loading="lazy" />
                    <span className="play">▶</span>
                  </button>
                )}
              </div>
              <div className="row between">
                <div>
                  <div className="strong">{v.title}</div>
                  <div className="muted small">{formatDate(v.event_date)}</div>
                </div>
                {isTeacher && <button className="btn small ghost" onClick={() => remove(v)}>삭제</button>}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
