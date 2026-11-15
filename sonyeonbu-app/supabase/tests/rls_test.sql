\set ON_ERROR_STOP 1
set client_min_messages = warning;
-- 4 users: first = admin automatically
insert into auth.users (id, raw_user_meta_data) values ('00000000-0000-0000-0000-00000000000a', '{"name":"관리자"}');
insert into auth.users (id, raw_user_meta_data) values ('00000000-0000-0000-0000-00000000000b', '{"name":"교사"}');
insert into auth.users (id, raw_user_meta_data) values ('00000000-0000-0000-0000-00000000000c', '{"name":"학부모"}');
insert into auth.users (id, raw_user_meta_data) values ('00000000-0000-0000-0000-00000000000d', '{"name":"대기자"}');
select name, role from profiles order by id;

create function pg_temp.as_user(u text) returns void language sql as $$ select set_config('test.uid', u, false) $$;
create table public.results (test text, pass boolean);
grant all on public.results to authenticated, anon;

-- admin approves b as teacher, c as member
set role authenticated; select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
update profiles set role='teacher' where id='00000000-0000-0000-0000-00000000000b';
update profiles set role='member'  where id='00000000-0000-0000-0000-00000000000c';
insert into results select 'admin sees all profiles', count(*)=4 from profiles;

-- teacher
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
insert into students (name, guardian_phone) values ('홍길동', '010-1111-2222');
insert into albums (title) values ('여름성경학교');
insert into photos (album_id, path, thumb_path) select id, 'x/1.jpg', 'x/1_t.jpg' from albums;
insert into videos (title, youtube_id) values ('찬양', 'dQw4w9WgXcQ');
insert into storage.objects (bucket_id, name) values ('student-photos', 's/1.jpg'), ('album', 'x/1.jpg');
insert into results select 'teacher sees students', count(*)=1 from students;
insert into results select 'teacher sees only own profile', count(*)=1 from profiles;
do $$ begin
  update profiles set role='admin' where id=auth.uid();
  insert into results values ('teacher cannot self-promote', false);
exception when others then insert into results values ('teacher cannot self-promote', true); end $$;

-- member (parent)
select pg_temp.as_user('00000000-0000-0000-0000-00000000000c');
insert into results select 'member cannot see students', count(*)=0 from students;
insert into results select 'member sees albums', count(*)=1 from albums;
insert into results select 'member sees photos', count(*)=1 from photos;
insert into results select 'member sees videos', count(*)=1 from videos;
insert into results select 'member sees album files only', count(*)=1 and bool_and(bucket_id='album') from storage.objects;
do $$ begin
  insert into albums (title) values ('hack');
  insert into results values ('member cannot create album', false);
exception when others then insert into results values ('member cannot create album', true); end $$;
do $$ begin
  insert into storage.objects (bucket_id, name) values ('album', 'evil.jpg');
  insert into results values ('member cannot upload', false);
exception when others then insert into results values ('member cannot upload', true); end $$;
do $$ begin
  update profiles set role='teacher' where id=auth.uid();
  insert into results values ('member cannot self-promote', false);
exception when others then insert into results values ('member cannot self-promote', true); end $$;
update profiles set name='학부모2' where id=auth.uid();
insert into results select 'member can edit own name', count(*)=1 from profiles where name='학부모2';
with d as (delete from albums returning 1) insert into results select 'member cannot delete albums', count(*)=0 from d;

-- pending
select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
insert into results select 'pending sees no albums', count(*)=0 from albums;
insert into results select 'pending sees no students', count(*)=0 from students;
insert into results select 'pending sees no files', count(*)=0 from storage.objects;
insert into results select 'pending sees own profile', count(*)=1 from profiles;

-- anon
reset role; set role anon; select pg_temp.as_user('');
do $$ begin
  perform * from students;
  insert into results values ('anon blocked', false);
exception when others then insert into results values ('anon blocked', true); end $$;
reset role;
select * from results order by pass, test;
select count(*) filter (where not pass) as failures from results;
