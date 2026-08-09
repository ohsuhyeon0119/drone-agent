/* 로그인·회원가입이 함께 쓰는 좌우 분할.
   넓은 화면에서 카드 하나만 띄우면 기준 글자 크기(26px)에 비해 폭이 좁아 제목과
   설명이 전부 두세 줄로 접힌다. 브랜드 면과 입력 면을 나눠 가로를 실제로 쓴다. */
export default function AuthLayout({ title, sub, children }) {
  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-[1.1fr_1fr]">
      {/* items-center는 내용이 칸보다 길면 위아래를 잘라낸다(스크롤로도 못 본다).
          m-auto는 넘칠 때 잘리지 않고 스크롤이 걸린다. */}
      <section className="bg-accent text-white flex overflow-y-auto px-10 sm:px-14 xl:px-20 py-12">
        <div className="max-w-[720px] m-auto">
          <div className="text-[21px] font-bold tracking-[0.22em] text-white/70 mb-6">
            DONGHAENG
          </div>
          <h1 className="text-[46px] xl:text-[56px] font-bold leading-[1.25] [text-wrap:balance]">
            노후를 함께 나는 동행자
          </h1>
          <p className="text-[26px] text-white/85 mt-5 leading-relaxed [text-wrap:pretty]">
            카메라와 목소리로 어르신 곁을 지키는 돌봄 에이전트를 설계합니다.
          </p>

          {/* 기준 글자가 26px이라 이 목록까지 넣으면 1280×800에서 아래가 잘린다.
              화면이 실제로 넓을 때만 보여준다 — 없어도 위 문장으로 충분하다. */}
          <dl className="hidden 2xl:grid gap-5 mt-10 border-t border-white/20 pt-8">
            {[
              ["지켜볼 상황", "낙상, 복약처럼 카메라가 찾을 장면"],
              ["대응 방식", "감지되면 할 말과 알릴 사람"],
              ["되돌리기", "배포한 설정은 버전으로 남습니다"],
            ].map(([term, desc]) => (
              /* grid여야 설명이 길어져도 항목 이름 열이 어긋나지 않는다. */
              <div key={term} className="grid grid-cols-[190px_1fr] gap-x-5 items-baseline">
                <dt className="text-[25px] font-bold">{term}</dt>
                <dd className="text-[24px] text-white/70">{desc}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="flex overflow-y-auto px-10 sm:px-16 py-10">
        <div className="w-full max-w-[620px] m-auto">
          <h2 className="text-[38px] font-bold mb-1">{title}</h2>
          <p className="text-muted text-[26px] mb-8">{sub}</p>
          {children}
        </div>
      </section>
    </div>
  );
}
