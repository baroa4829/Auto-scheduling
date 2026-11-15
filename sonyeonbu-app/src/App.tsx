import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth, useRole } from './auth';
import { configured } from './supabase';
import Layout from './components/Layout';
import Login from './pages/Login';
import ResetPassword from './pages/ResetPassword';
import Pending from './pages/Pending';
import Students from './pages/Students';
import StudentDetail from './pages/StudentDetail';
import StudentForm from './pages/StudentForm';
import Albums from './pages/Albums';
import AlbumDetail from './pages/AlbumDetail';
import Videos from './pages/Videos';
import Admin from './pages/Admin';
import Me from './pages/Me';

export default function App() {
  const { session, profile, loading } = useAuth();
  const { isMember, isTeacher, isAdmin } = useRole();

  if (!configured) {
    return (
      <div className="center-screen">
        <div className="card narrow">
          <h1>설정이 필요합니다</h1>
          <p className="muted">
            <code>.env</code> 파일에 <code>VITE_SUPABASE_URL</code>, <code>VITE_SUPABASE_ANON_KEY</code>를 입력한 뒤
            다시 실행해 주세요. 자세한 방법은 README를 참고하세요.
          </p>
        </div>
      </div>
    );
  }

  if (loading) return <div className="center-screen muted">불러오는 중…</div>;

  return (
    <Routes>
      <Route path="/reset" element={<ResetPassword />} />
      {!session ? (
        <Route path="*" element={<Login />} />
      ) : !profile || !isMember ? (
        <Route path="*" element={<Pending />} />
      ) : (
        <Route element={<Layout />}>
          <Route index element={<Navigate to={isTeacher ? '/students' : '/albums'} replace />} />
          {isTeacher && (
            <>
              <Route path="students" element={<Students />} />
              <Route path="students/new" element={<StudentForm />} />
              <Route path="students/:id" element={<StudentDetail />} />
              <Route path="students/:id/edit" element={<StudentForm />} />
            </>
          )}
          <Route path="albums" element={<Albums />} />
          <Route path="albums/:id" element={<AlbumDetail />} />
          <Route path="videos" element={<Videos />} />
          {isAdmin && <Route path="admin" element={<Admin />} />}
          <Route path="me" element={<Me />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      )}
    </Routes>
  );
}
