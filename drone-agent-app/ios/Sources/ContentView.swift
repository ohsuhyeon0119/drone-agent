import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var model = AppModel()
    @EnvironmentObject private var auth: AuthStore
    @State private var showSettings = false
    @State private var serverDraft = ""
    /// 기록은 기본으로 감춰둔다 — 어르신이 보는 화면은 카메라여야 한다.
    @State private var showLog = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CameraPreview(session: model.camera.session).ignoresSafeArea()

            VStack(spacing: 12) {
                header

                Spacer(minLength: 0)

                if let alert = model.alertText {
                    banner(alert)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                if showLog { logPanel }
                if !model.caption.isEmpty {
                    captionView
                }

                controls
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showSettings) { settingsSheet }
        .animation(.easeOut(duration: 0.2), value: model.alertText)
        .animation(.easeOut(duration: 0.2), value: showLog)
        .task {
            UIApplication.shared.isIdleTimerDisabled = true
            model.use(deviceToken: auth.token)
            await model.prepareCamera()
        }
    }

    // MARK: - 조각들

    private var header: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(model.isLive ? Color.green : Color.white.opacity(0.35))
                .frame(width: 9, height: 9)
            Text(model.status)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.white)
            Spacer()
            Button {
                showLog.toggle()
            } label: {
                Image(systemName: showLog ? "list.bullet.rectangle.fill" : "list.bullet.rectangle")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(showLog ? Color.accentColor : .white)
                    .frame(width: 38, height: 38)
                    .background(.black.opacity(0.45), in: Circle())
            }
            .accessibilityLabel(showLog ? "기록 숨기기" : "기록 보기")
            Button {
                model.flipCamera()
            } label: {
                Image(systemName: "arrow.triangle.2.circlepath.camera")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(.black.opacity(0.45), in: Circle())
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 4)
        .padding(.vertical, 4)
        .background(.black.opacity(0.45), in: Capsule())
        // 어르신이 실수로 열 일이 없도록 길게 눌러야만 연결 설정이 나온다.
        .onLongPressGesture(minimumDuration: 1.2) {
            serverDraft = Config.serverBase
            showSettings = true
        }
    }

    /// 연결 설정 — 서버 주소 변경과 코드 재입력.
    ///
    /// 이 둘이 로그인 화면에만 있으면, 한 번 연결한 뒤에는 서버를 바꿀 방법이
    /// 없어진다(로그아웃해야 하는데 로그아웃도 같은 화면에 숨어 있었다).
    private var settingsSheet: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://droneagent.cloud", text: $serverDraft)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.system(size: 16, design: .monospaced))
                } header: {
                    Text("서버 주소")
                } footer: {
                    Text("맥북 로컬 서버는 `http://<맥 IP>:8004` 형태입니다.")
                }

                Section {
                    Button("코드 다시 입력") {
                        model.stopIfLive()
                        showSettings = false
                        auth.signOut()
                    }
                    .foregroundStyle(.red)
                } footer: {
                    Text(auth.elderName.isEmpty
                         ? "현재 코드 \(auth.code)로 연결되어 있습니다."
                         : "현재 \(auth.elderName) 어르신(코드 \(auth.code))으로 연결되어 있습니다.")
                }
            }
            .navigationTitle("연결 설정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("취소") { showSettings = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("저장") {
                        Config.serverBase = serverDraft
                        // 주소가 바뀌면 지금 세션은 옛 서버를 보고 있다 — 끊어야 한다.
                        model.stopIfLive()
                        showSettings = false
                    }
                }
            }
        }
    }

    /// 카메라 위에 겹치는 반투명 기록 패널.
    /// 실시간 감지 상태는 위쪽에 고정하고, 그 아래로 지나간 일을 쌓는다.
    private var logPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(model.detectionOrder, id: \.self) { key in
                if let line = model.detections[key] {
                    Text(line)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.white.opacity(0.85))
                        .lineLimit(2)
                }
            }

            if !model.detectionOrder.isEmpty && !model.logLines.isEmpty {
                Divider().overlay(.white.opacity(0.25))
            }

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 6) {
                        ForEach(model.logLines) { line in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(line.time)
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.white.opacity(0.45))
                                Text(line.text)
                                    .font(.system(size: 12,
                                                  weight: line.emphasized ? .bold : .regular))
                                    .foregroundStyle(.white.opacity(line.emphasized ? 0.95 : 0.7))
                            }
                            .id(line.id)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 190)
                // 새 줄이 쌓이면 따라 내려간다 — 손으로 계속 스크롤하게 두면 못 읽는다.
                .onChange(of: model.logLines.count) { _, _ in
                    if let last = model.logLines.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }

            if model.logLines.isEmpty && model.detectionOrder.isEmpty {
                Text("아직 기록이 없습니다.")
                    .font(.system(size: 12))
                    .foregroundStyle(.white.opacity(0.5))
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial.opacity(0.9), in: RoundedRectangle(cornerRadius: 16))
        .environment(\.colorScheme, .dark)
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func banner(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 15, weight: .bold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background((model.alertIsPositive ? Color.green : Color.red).opacity(0.9),
                        in: RoundedRectangle(cornerRadius: 14))
    }

    private func chip(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(.white.opacity(0.9))
            .lineLimit(2)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(.black.opacity(0.5), in: Capsule())
    }

    private var captionView: some View {
        Text(model.caption)
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(.white)
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 16))
    }

    private var controls: some View {
        Button {
            model.toggle()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: model.isLive ? "stop.fill" : "mic.fill")
                Text(model.isLive ? "대화 종료" : "대화 시작")
            }
            .font(.system(size: 18, weight: .bold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(height: 58)
            .background(model.isLive ? Color.red : Color.accentColor,
                        in: RoundedRectangle(cornerRadius: 18))
        }
        .disabled(model.isBusy)
        .opacity(model.isBusy ? 0.6 : 1)
    }
}

#Preview {
    RootView()
}
