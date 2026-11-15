import { NavLink, Outlet } from 'react-router-dom';
import { useRole } from '../auth';

export default function Layout() {
  const { isTeacher, isAdmin } = useRole();
  const tabs = [
    ...(isTeacher ? [{ to: '/students', label: '요람', icon: '📇' }] : []),
    { to: '/albums', label: '앨범', icon: '🖼️' },
    { to: '/videos', label: '영상', icon: '🎬' },
    ...(isAdmin ? [{ to: '/admin', label: '회원관리', icon: '🔑' }] : []),
    { to: '/me', label: '내 정보', icon: '👤' },
  ];
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">동석교회 소년부</span>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <nav className="tabbar" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}>
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => 'tab' + (isActive ? ' active' : '')}>
            <span className="tab-icon" aria-hidden>{t.icon}</span>
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
