import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { useStore } from "../store.jsx";

const MENU = [
  { to: "/monitor", label: "모니터링", icon: IconMonitor },
  { to: "/scenarios", label: "시나리오", icon: IconEye },
  { to: "/actions", label: "행동", icon: IconHand },
  { to: "/contacts", label: "알림 연락처", icon: IconPhone },
  { to: "/deploy", label: "배포", icon: IconShip },
];


function IconMonitor() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="4" width="20" height="13" rx="2" /><path d="M8 21h8m-4-4v4" />
    </svg>
  );
}
function IconEye() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function IconHand() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 11V5a1.5 1.5 0 0 1 3 0v5m0-3a1.5 1.5 0 0 1 3 0v4m0-2a1.5 1.5 0 0 1 3 0v5a7 7 0 0 1-7 7h-1a7 7 0 0 1-6-3.5L2.5 14a1.6 1.6 0 0 1 2.7-1.6L6.5 14V7a1.5 1.5 0 0 1 3 0" transform="translate(1.5 0)" />
    </svg>
  );
}
function IconPhone() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.13.96.36 1.9.7 2.8a2 2 0 0 1-.45 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.25a2 2 0 0 1 2.1-.45c.9.34 1.84.57 2.8.7a2 2 0 0 1 1.7 2Z" />
    </svg>
  );
}
function IconShip() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v9m0-9 4 4m-4-4L8 7" /><path d="M4 13.5 12 12l8 1.5M5 13l1.8 6.3A2 2 0 0 0 8.7 21h6.6a2 2 0 0 0 1.9-1.7L19 13" />
    </svg>
  );
}
function IconClock() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
    </svg>
  );
}
function IconChevron({ open }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      style={{ transform: open ? "rotate(180deg)" : "none" }}>
      <path d="m15 6-6 6 6 6" />
    </svg>
  );
}

function IconLogout() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" />
    </svg>
  );
}

function IconMenu() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

export default function Layout() {
  const [open, setOpen] = useState(true); // 데스크톱: 접힘/펼침
  const [mobileOpen, setMobileOpen] = useState(false); // 모바일: 오버레이
  const { live, changes, ready, error, saving } = useStore();
  const { logout, user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen md:flex">
      {/* 모바일 상단 바 */}
      <header className="md:hidden sticky top-0 z-30 flex items-center justify-between h-14 px-3 bg-surface border-b border-line">
        <button
          aria-label="메뉴 열기"
          onClick={() => setMobileOpen(true)}
          className="w-11 h-11 flex items-center justify-center rounded-(--radius-ctl) text-ink cursor-pointer"
        >
          <IconMenu />
        </button>
        <div className="font-bold text-[16px]">에이전트 관리</div>
        <button
          onClick={() => navigate("/deploy")}
          className={`h-9 px-3 rounded-full text-[15px] font-bold tabular-nums cursor-pointer
            ${changes.length ? "bg-warnsoft text-warn" : "bg-accentsoft text-accent"}`}
        >
          v{live.version}{changes.length > 0 && ` · ${changes.length}`}
        </button>
      </header>

      {/* 모바일 오버레이 배경 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink/40 md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        /* 본문이 길면 사이드바도 페이지 높이만큼 늘어나서, 아래에 붙인 계정·로그아웃이
           화면 밖으로 밀려 보이지 않는다. 화면 높이에 고정하고 안쪽에서만 스크롤한다. */
        className={`flex flex-col bg-surface border-r border-line transition-[width,transform] duration-200
          fixed inset-y-0 left-0 z-50 w-[240px]
          md:sticky md:top-0 md:h-screen md:self-start md:z-auto md:flex-none md:translate-x-0
          ${mobileOpen ? "translate-x-0" : "-translate-x-full"}
          ${open ? "md:w-[240px]" : "md:w-[72px]"}`}
      >
        <SidebarContent
          open={open}
          setOpen={setOpen}
          closeMobile={() => setMobileOpen(false)}
          live={live}
          changes={changes}
          navigate={navigate}
          logout={logout}
          user={user}
          saving={saving}
        />
      </aside>

      <main className="flex-1 min-w-0">
        <div className="w-full px-4 sm:px-10 py-6 sm:py-12">
          {/* 설정을 서버에서 받아오기 전에 화면을 그리면 "시나리오 없음"이 잠깐
              보였다가 채워진다 — 지운 줄 알고 다시 만들게 된다. */}
          {ready ? <Outlet /> : (
            <p className="text-muted text-[19px] py-10">설정을 불러오는 중…</p>
          )}
          {error && (
            <p role="alert"
               className="mt-6 text-warn text-[18px] bg-warnsoft border border-warn/30 rounded-(--radius-card) px-6 py-4">
              {error}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}

function SidebarContent({ open, setOpen, closeMobile, live, changes, navigate, logout, user, saving }) {
  // 모바일 오버레이는 항상 펼친 폭(w-64)이므로 라벨을 항상 보여준다.
  // md 미만에서는 open 상태와 무관하게 라벨 표시 — CSS로 제어.
  const labelCls = open ? "" : "md:hidden";
  return (
    <>
      <div className={`flex items-center h-[74px] border-b border-line px-5 ${open ? "justify-between" : "md:px-0 md:justify-center justify-between"}`}>
        <div className={`leading-tight ${labelCls}`}>
          <div className="font-bold text-[22px] whitespace-nowrap">에이전트 관리</div>
          <div className="text-[13px] text-muted mt-1 whitespace-nowrap">함께 나는 에이전트</div>
        </div>
        <button
          aria-label={open ? "메뉴 접기" : "메뉴 펼치기"}
          onClick={() => setOpen(!open)}
          className="hidden md:flex w-11 h-11 items-center justify-center rounded-(--radius-ctl) text-muted hover:text-ink cursor-pointer"
        >
          <IconChevron open={open} />
        </button>
        <button
          aria-label="메뉴 닫기"
          onClick={closeMobile}
          className="md:hidden w-11 h-11 flex items-center justify-center rounded-(--radius-ctl) text-muted cursor-pointer"
        >
          ✕
        </button>
      </div>

      <nav className="flex-1 min-h-0 overflow-y-auto py-4 flex flex-col gap-1 px-3">
        {MENU.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            onClick={closeMobile}
            className={({ isActive }) =>
              `flex items-center gap-3.5 h-14 text-[19px] rounded-(--radius-ctl) transition-colors duration-150 px-4
               ${open ? "" : "md:px-0 md:justify-center"}
               ${isActive ? "bg-accentsoft text-accent font-semibold" : "text-muted hover:text-ink"}`
            }
          >
            <Icon />
            <span className={labelCls}>{label}</span>
          </NavLink>
        ))}
        <div
          title="활동 기록 (준비 중)"
          className={`flex items-center gap-3.5 h-14 text-[19px] rounded-(--radius-ctl) text-muted/45 cursor-not-allowed px-4
            ${open ? "" : "md:px-0 md:justify-center"}`}
        >
          <IconClock />
          <span className={`whitespace-nowrap ${labelCls}`}>
            활동 기록 <span className="text-[14px]">· 준비 중</span>
          </span>
        </div>

        {/* 계정마다 돌보는 어르신이 다르므로, 어느 계정으로 들어와 있는지 보여야
            엉뚱한 곳에 설정을 배포하는 일이 없다. */}
        <div className="mt-auto pt-3 border-t border-line">
          {user && (
            <div className={`px-4 pb-2 ${labelCls}`}>
              <div className="text-[18px] font-bold truncate">{user.name}</div>
              <div className="text-[14px] text-muted truncate" title={user.email}>
                {user.email}
              </div>
            </div>
          )}
          <button
            onClick={() => { closeMobile(); logout(); navigate("/login", { replace: true }); }}
            title={user ? `로그아웃 (${user.email})` : "로그아웃"}
            className={`w-full flex items-center gap-3.5 h-14 text-[19px] rounded-(--radius-ctl) px-4
              text-muted hover:text-ink transition-colors duration-150 cursor-pointer
              ${open ? "" : "md:px-0 md:justify-center"}`}
          >
            <IconLogout />
            <span className={labelCls}>로그아웃</span>
          </button>
        </div>
      </nav>

      <button
        onClick={() => { closeMobile(); navigate("/deploy"); }}
        className={`m-3 rounded-(--radius-ctl) border text-left cursor-pointer transition-colors duration-150 px-4 py-3
          ${changes.length ? "border-warn/40 bg-warnsoft hover:border-warn" : "border-line bg-bg hover:border-accent"}
          ${open ? "" : "md:px-0 md:flex md:justify-center"}`}
      >
        <span className={labelCls}>
          <span className="block text-[15px] tracking-wide text-muted">
            현재 적용 버전{saving && <span className="ml-2">저장 중…</span>}
          </span>
          <span className="font-bold tabular-nums text-[19px]">
            Live v{live.version}
            {changes.length > 0 && (
              <span className="text-warn font-semibold"> · 수정 {changes.length}건</span>
            )}
          </span>
        </span>
        {!open && (
          <span className="hidden md:inline font-bold tabular-nums text-[18px]">v{live.version}</span>
        )}
      </button>
    </>
  );
}
