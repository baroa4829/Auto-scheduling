-- =====================================================================
-- 동석교회 소년부 요람 앱 - 데이터베이스 스키마 + 권한(RLS)
-- Supabase 대시보드 > SQL Editor 에 전체를 붙여넣고 Run 하세요.
-- 여러 번 실행해도 안전하도록 작성되어 있습니다.
-- =====================================================================

-- ---------- 역할 ----------
-- pending : 가입만 하고 승인 대기 (아무것도 못 봄)
-- member  : 일반 구성원 (앨범/영상 조회)
-- teacher : 교사 (요람 조회/수정 + 앨범/영상 업로드)
-- admin   : 관리자 (교사 권한 + 회원 승인/역할 변경)
do $$ begin
  create type public.user_role as enum ('pending', 'member', 'teacher', 'admin');
exception when duplicate_object then null; end $$;

-- ---------- 회원 프로필 ----------
create table if not exists public.profiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  name       text not null default '',
  phone      text,
  role       public.user_role not null default 'pending',
  created_at timestamptz not null default now()
);

-- ---------- 권한 확인 함수 ----------
create or replace function public.my_role() returns public.user_role
language sql stable security definer set search_path = public as $$
  select role from public.profiles where id = auth.uid()
$$;

create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce(public.my_role() in ('member', 'teacher', 'admin'), false)
$$;

create or replace function public.is_teacher() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce(public.my_role() in ('teacher', 'admin'), false)
$$;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce(public.my_role() = 'admin', false)
$$;

-- ---------- 가입 시 프로필 자동 생성 ----------
-- 맨 처음 가입한 사람은 자동으로 관리자가 됩니다. (그 뒤로는 모두 승인 대기)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform pg_advisory_xact_lock(4829);
  insert into public.profiles (id, name, phone, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'name', ''),
    new.raw_user_meta_data->>'phone',
    case when exists (select 1 from public.profiles where role = 'admin')
         then 'pending'::public.user_role else 'admin'::public.user_role end
  );
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 본인이 자기 역할을 바꾸는 것을 막음 (관리자만 역할 변경 가능)
create or replace function public.protect_role() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.role is distinct from old.role and not public.is_admin() then
    raise exception '역할은 관리자만 변경할 수 있습니다.';
  end if;
  if new.id is distinct from old.id then
    raise exception 'id는 변경할 수 없습니다.';
  end if;
  return new;
end $$;

drop trigger if exists profiles_protect_role on public.profiles;
create trigger profiles_protect_role
  before update on public.profiles
  for each row execute function public.protect_role();

-- ---------- 요람 (아이 정보) ----------
create table if not exists public.students (
  id               uuid primary key default gen_random_uuid(),
  name             text not null,
  gender           text check (gender in ('남', '여')),
  birth_date       date,
  class_name       text,             -- 예: '5학년 1반'
  school           text,
  student_phone    text,
  guardian_name    text,
  guardian_relation text,            -- 예: '모', '부'
  guardian_phone   text,
  address          text,
  notes            text,             -- 알레르기, 기도제목 등
  photo_path       text,             -- storage: student-photos 버킷 경로
  consent_info     boolean not null default false, -- 개인정보 수집 동의서 받음
  consent_photo    boolean not null default false, -- 앨범 사진 공개 동의
  created_by       uuid references auth.users(id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;

drop trigger if exists students_touch on public.students;
create trigger students_touch before update on public.students
  for each row execute function public.touch_updated_at();

-- ---------- 앨범 / 사진 / 영상 ----------
create table if not exists public.albums (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  event_date  date,
  description text,
  created_by  uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now()
);

create table if not exists public.photos (
  id          uuid primary key default gen_random_uuid(),
  album_id    uuid not null references public.albums(id) on delete cascade,
  path        text not null,          -- storage: album 버킷 경로 (원본)
  thumb_path  text not null,          -- storage: album 버킷 경로 (썸네일)
  caption     text,
  uploaded_by uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now()
);
create index if not exists photos_album_idx on public.photos(album_id, created_at);

create table if not exists public.videos (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  youtube_id  text not null check (youtube_id ~ '^[A-Za-z0-9_-]{6,20}$'),
  description text,
  event_date  date,
  created_by  uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now()
);

-- =====================================================================
-- 행 단위 보안 (RLS)
-- =====================================================================
alter table public.profiles enable row level security;
alter table public.students enable row level security;
alter table public.albums   enable row level security;
alter table public.photos   enable row level security;
alter table public.videos   enable row level security;

-- profiles: 본인 것 조회/수정, 관리자는 전체
drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_admin());
drop policy if exists profiles_update on public.profiles;
create policy profiles_update on public.profiles for update to authenticated
  using (id = auth.uid() or public.is_admin())
  with check (id = auth.uid() or public.is_admin());
drop policy if exists profiles_delete on public.profiles;
create policy profiles_delete on public.profiles for delete to authenticated
  using (public.is_admin() and id <> auth.uid());

-- students: 교사/관리자만 (조회 포함 전부)
drop policy if exists students_all on public.students;
create policy students_all on public.students for all to authenticated
  using (public.is_teacher()) with check (public.is_teacher());

-- albums / photos / videos: 승인된 구성원 조회, 교사/관리자 등록·수정·삭제
do $$
declare t text;
begin
  foreach t in array array['albums', 'photos', 'videos'] loop
    execute format('drop policy if exists %1$s_select on public.%1$s', t);
    execute format('create policy %1$s_select on public.%1$s for select to authenticated using (public.is_member())', t);
    execute format('drop policy if exists %1$s_write on public.%1$s', t);
    execute format('create policy %1$s_write on public.%1$s for insert to authenticated with check (public.is_teacher())', t);
    execute format('drop policy if exists %1$s_update on public.%1$s', t);
    execute format('create policy %1$s_update on public.%1$s for update to authenticated using (public.is_teacher()) with check (public.is_teacher())', t);
    execute format('drop policy if exists %1$s_delete on public.%1$s', t);
    execute format('create policy %1$s_delete on public.%1$s for delete to authenticated using (public.is_teacher())', t);
  end loop;
end $$;

-- 비로그인(anon) 사용자는 어떤 테이블도 접근 불가
revoke all on public.profiles, public.students, public.albums, public.photos, public.videos from anon;

-- =====================================================================
-- 사진 저장소 (Storage) - 두 버킷 모두 비공개(private)
-- =====================================================================
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('student-photos', 'student-photos', false, 5242880, array['image/jpeg', 'image/png', 'image/webp']),
  ('album',          'album',          false, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update set public = false;

drop policy if exists "student photos: teachers" on storage.objects;
create policy "student photos: teachers" on storage.objects for all to authenticated
  using (bucket_id = 'student-photos' and public.is_teacher())
  with check (bucket_id = 'student-photos' and public.is_teacher());

drop policy if exists "album: members read" on storage.objects;
create policy "album: members read" on storage.objects for select to authenticated
  using (bucket_id = 'album' and public.is_member());

drop policy if exists "album: teachers write" on storage.objects;
create policy "album: teachers write" on storage.objects for insert to authenticated
  with check (bucket_id = 'album' and public.is_teacher());

drop policy if exists "album: teachers update" on storage.objects;
create policy "album: teachers update" on storage.objects for update to authenticated
  using (bucket_id = 'album' and public.is_teacher());

drop policy if exists "album: teachers delete" on storage.objects;
create policy "album: teachers delete" on storage.objects for delete to authenticated
  using (bucket_id = 'album' and public.is_teacher());
