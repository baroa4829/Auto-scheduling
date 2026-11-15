import { useAuth } from '../auth';

export default function Pending() {
  const { profile, refresh, signOut } = useAuth();
  return (
    <div className="center-screen">
      <div className="card narrow center">
        <div style={{ fontSize: 48 }}>⏳</div>
        <h1>승인 대기 중</h1>
        <p className="muted">
          {profile?.name ? `${profile.name}님, ` : ''}가입 신청이 접수되었습니다.
          <br />
          관리자(소년부 담당 선생님)가 승인하면 이용할 수 있습니다.
        </p>
        <div className="row gap center">
          <button className="btn" onClick={refresh}>다시 확인</button>
          <button className="btn ghost" onClick={signOut}>로그아웃</button>
        </div>
      </div>
    </div>
  );
}
