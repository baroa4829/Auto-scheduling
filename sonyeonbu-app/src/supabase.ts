import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const configured = Boolean(url && key);
export const supabase = createClient(url || 'http://localhost', key || 'missing');

export type Role = 'pending' | 'member' | 'teacher' | 'admin';

export interface Profile {
  id: string;
  name: string;
  phone: string | null;
  role: Role;
  created_at: string;
}

export interface Student {
  id: string;
  name: string;
  gender: '남' | '여' | null;
  birth_date: string | null;
  class_name: string | null;
  school: string | null;
  student_phone: string | null;
  guardian_name: string | null;
  guardian_relation: string | null;
  guardian_phone: string | null;
  address: string | null;
  notes: string | null;
  photo_path: string | null;
  consent_info: boolean;
  consent_photo: boolean;
}

export interface Album {
  id: string;
  title: string;
  event_date: string | null;
  description: string | null;
  created_at: string;
}

export interface Photo {
  id: string;
  album_id: string;
  path: string;
  thumb_path: string;
  caption: string | null;
  created_at: string;
}

export interface Video {
  id: string;
  title: string;
  youtube_id: string;
  description: string | null;
  event_date: string | null;
  created_at: string;
}

export const ROLE_LABEL: Record<Role, string> = {
  pending: '승인 대기',
  member: '구성원',
  teacher: '교사',
  admin: '관리자',
};

/** 비공개 버킷 파일들의 임시 URL(1시간) 발급 */
export async function signedUrls(bucket: string, paths: string[]): Promise<Record<string, string>> {
  const unique = [...new Set(paths.filter(Boolean))];
  if (unique.length === 0) return {};
  const { data, error } = await supabase.storage.from(bucket).createSignedUrls(unique, 3600);
  if (error || !data) return {};
  const map: Record<string, string> = {};
  for (const item of data) if (item.path && item.signedUrl) map[item.path] = item.signedUrl;
  return map;
}
