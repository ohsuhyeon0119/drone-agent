import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useStore } from "../store.jsx";

const MENU = [
  { to: "/agent", label: "에이전트", icon: IconAgent },
  { to: "/scenarios", label: "시나리오", icon: IconEye },
  { to: "/actions", label: "행동", icon: IconHand },
  { to: "/contacts", label: "알림 연락처", icon: IconPhone },
  { to: "/deploy", label: "배포", icon: IconShip },
];

function IconAgent() {
  return (
    <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="7" width="18" height="12" rx="3" />
      <path d="M12 3v4M8 12h.01M16 12h.01M9.5 15.5c1.5 1 3.5 1 5 0" />
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
  const { live, changes } = useStore();
  const navigate = useNavigate();
  const onAgentPage = useLocation().pathname.startsWith("/agent");

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
        <div className="font-bold text-[22px]">에이전트 관리</div>
        <button
          onClick={() => navigate("/deploy")}
          className={`h-9 px-3 rounded-full text-[20px] font-bold tabular-nums cursor-pointer
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
        className={`flex flex-col bg-surface border-r border-line transition-[width,transform] duration-200
          fixed inset-y-0 left-0 z-50 w-[280px] md:static md:z-auto md:flex-none md:translate-x-0
          ${mobileOpen ? "translate-x-0" : "-translate-x-full"}
          ${open ? "md:w-[330px]" : "md:w-[96px]"}`}
      >
        <SidebarContent
          open={open}
          setOpen={setOpen}
          closeMobile={() => setMobileOpen(false)}
          live={live}
          changes={changes}
          navigate={navigate}
        />
      </aside>

      <main className="flex-1 min-w-0">
        {/* 에이전트 화면은 임베드된 앱이 폭을 최대한 쓰도록 여백을 줄인다 */}
        <div className={onAgentPage
          ? "w-full px-3 sm:px-5 py-4 sm:py-6"
          : "w-full px-4 sm:px-10 py-6 sm:py-12"}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function SidebarContent({ open, setOpen, closeMobile, live, changes, navigate }) {
  // 모바일 오버레이는 항상 펼친 폭(w-64)이므로 라벨을 항상 보여준다.
  // md 미만에서는 open 상태와 무관하게 라벨 표시 — CSS로 제어.
  const labelCls = open ? "" : "md:hidden";
  return (
    <>
      <div className={`flex items-center h-[104px] border-b border-line px-5 ${open ? "justify-between" : "md:px-0 md:justify-center justify-between"}`}>
        <div className={`leading-tight ${labelCls}`}>
          <div className="font-bold text-[30px] whitespace-nowrap">에이전트 관리</div>
          <div className="text-[17px] text-muted mt-1 whitespace-nowrap">함께 나는 에이전트</div>
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

      <nav className="flex-1 py-4 flex flex-col gap-1 px-3">
        {MENU.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            onClick={closeMobile}
            className={({ isActive }) =>
              `flex items-center gap-3.5 h-14 text-[26px] rounded-(--radius-ctl) transition-colors duration-150 px-4
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
          className={`flex items-center gap-3.5 h-14 text-[26px] rounded-(--radius-ctl) text-muted/45 cursor-not-allowed px-4
            ${open ? "" : "md:px-0 md:justify-center"}`}
        >
          <IconClock />
          <span className={`whitespace-nowrap ${labelCls}`}>
            활동 기록 <span className="text-[18px]">· 준비 중</span>
          </span>
        </div>
      </nav>

      <button
        onClick={() => { closeMobile(); navigate("/deploy"); }}
        className={`m-3 rounded-(--radius-ctl) border text-left cursor-pointer transition-colors duration-150 px-4 py-3
          ${changes.length ? "border-warn/40 bg-warnsoft hover:border-warn" : "border-line bg-bg hover:border-accent"}
          ${open ? "" : "md:px-0 md:flex md:justify-center"}`}
      >
        <span className={labelCls}>
          <span className="block text-[20px] tracking-wide text-muted">현재 적용 버전</span>
          <span className="font-bold tabular-nums text-[26px]">
            Live v{live.version}
            {changes.length > 0 && (
              <span className="text-warn font-semibold"> · 수정 {changes.length}건</span>
            )}
          </span>
        </span>
        {!open && (
          <span className="hidden md:inline font-bold tabular-nums text-[24px]">v{live.version}</span>
        )}
      </button>
    </>
  );
}
