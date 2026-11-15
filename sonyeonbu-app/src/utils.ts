/** 사진을 지정한 최대 크기로 줄여 JPEG로 변환 (저장 공간 절약) */
export async function resizeImage(file: File, maxSize: number, quality = 0.85): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' } as ImageBitmapOptions);
  const scale = Math.min(1, maxSize / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('이미지를 처리할 수 없습니다.');
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('이미지 변환 실패'))), 'image/jpeg', quality),
  );
}

/** 유튜브 주소에서 영상 ID 추출 (watch, youtu.be, shorts, live, embed 모두 지원) */
export function parseYouTubeId(input: string): string | null {
  const s = input.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  try {
    const u = new URL(s);
    const host = u.hostname.replace(/^(www\.|m\.|music\.)/, '');
    if (host === 'youtu.be') return valid(u.pathname.slice(1).split('/')[0]);
    if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
      const v = u.searchParams.get('v');
      if (v) return valid(v);
      const m = u.pathname.match(/^\/(?:shorts|live|embed)\/([^/?#]+)/);
      if (m) return valid(m[1]);
    }
  } catch {
    /* not a URL */
  }
  return null;
}

function valid(id: string | undefined): string | null {
  return id && /^[A-Za-z0-9_-]{6,20}$/.test(id) ? id : null;
}

export function telHref(phone: string) {
  return 'tel:' + phone.replace(/[^0-9+]/g, '');
}

export function formatDate(d: string | null) {
  if (!d) return '';
  const [y, m, day] = d.slice(0, 10).split('-');
  return `${y}.${m}.${day}`;
}

export function age(birth: string | null): string {
  if (!birth) return '';
  const b = new Date(birth);
  const now = new Date();
  let a = now.getFullYear() - b.getFullYear();
  if (now.getMonth() < b.getMonth() || (now.getMonth() === b.getMonth() && now.getDate() < b.getDate())) a--;
  return `만 ${a}세`;
}

export function errorMessage(e: unknown): string {
  const msg = e instanceof Error ? e.message : typeof e === 'object' && e && 'message' in e ? String((e as { message: unknown }).message) : String(e);
  if (/Invalid login credentials/i.test(msg)) return '이메일 또는 비밀번호가 올바르지 않습니다.';
  if (/Email not confirmed/i.test(msg)) return '이메일 인증이 아직 완료되지 않았습니다. 메일함을 확인해 주세요.';
  if (/already registered/i.test(msg)) return '이미 가입된 이메일입니다.';
  if (/Password should be at least/i.test(msg)) return '비밀번호는 6자 이상이어야 합니다.';
  if (/row-level security|permission denied/i.test(msg)) return '권한이 없습니다.';
  return msg;
}
