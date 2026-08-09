import SwiftUI
import UIKit

/// 케어 콘솔(웹)의 디자인 언어를 세로 화면으로 옮긴 토큰.
/// 콘솔은 좌우 분할(블루 히어로 | 화이트 폼)인데, 폰에서는 위아래로 쌓는다.
enum LoginStyle {
    static let brand = Color(red: 0.247, green: 0.376, blue: 0.847)      // 로열 블루
    static let brandMuted = Color(red: 0.663, green: 0.737, blue: 0.937) // 비활성 버튼
    static let canvas = Color(red: 0.965, green: 0.969, blue: 0.976)     // 폼 영역 배경
    static let surface = Color.white
    static let ink = Color(red: 0.114, green: 0.129, blue: 0.176)
    static let inkSoft = Color(red: 0.420, green: 0.447, blue: 0.502)
    static let stroke = Color(red: 0.878, green: 0.894, blue: 0.914)
    static let danger = Color(red: 0.816, green: 0.204, blue: 0.173)

    /// 어르신 기준 하한 — 본문 17pt, 터치 타깃 60pt 이상.
    static let buttonHeight: CGFloat = 60
    static let boxHeight: CGFloat = 64
}

struct LoginView: View {
    @ObservedObject var auth: AuthStore

    @State private var code = ""
    @State private var errorText: String?
    @State private var isChecking = false
    @State private var showServerSheet = false
    @State private var serverDraft = ""
    @State private var serverLabel = Config.serverLabel
    @FocusState private var keyboardFocused: Bool

    private var length: Int { Config.accessCodeLength }
    private var isComplete: Bool { code.count == length }

    var body: some View {
        ZStack {
            LoginStyle.canvas.ignoresSafeArea()

            ScrollView {
                VStack(spacing: 0) {
                    hero
                    panel
                }
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .preferredColorScheme(.light)
        .sheet(isPresented: $showServerSheet) { serverSheet }
        .onAppear {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { keyboardFocused = true }
        }
    }

    // MARK: - 서버 주소 (개발용)

    private var serverSheet: some View {
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
                    Text("맥북 로컬 서버로 붙으려면 `http://<맥 IP>:8003` 형태로 넣으세요. "
                         + "같은 Wi-Fi에 있어야 하고, 처음 연결할 때 로컬 네트워크 접근을 허용해야 합니다.")
                }

                Section {
                    Button("기본값으로 되돌리기") {
                        serverDraft = Config.defaultServerBase
                    }
                }
            }
            .navigationTitle("연결 설정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("취소") { showServerSheet = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("저장") {
                        Config.serverBase = serverDraft
                        serverLabel = Config.serverLabel
                        errorText = nil
                        showServerSheet = false
                    }
                }
            }
        }
    }

    // MARK: - 블루 히어로

    private var hero: some View {
        VStack(alignment: .leading, spacing: 0) {
            // 길게 누르면 서버 주소를 바꿀 수 있다 — 어르신이 우연히 열 일은 없고,
            // 데모 중 클라우드↔로컬 전환은 재빌드 없이 즉시 돼야 한다.
            Text("DRONEAGENT")
                .font(.system(size: 13, weight: .semibold))
                .tracking(2.4)
                .foregroundStyle(.white.opacity(0.72))
                .onLongPressGesture(minimumDuration: 1.2) {
                    serverDraft = Config.serverBase
                    showServerSheet = true
                }

            Text("노후를 함께\n나는 동반자")
                .font(.system(size: 34, weight: .bold))
                .foregroundStyle(.white)
                .lineSpacing(4)
                .padding(.top, 14)

            Text("어르신의 곁을 지킵니다")
                .font(.system(size: 16, weight: .regular))
                .foregroundStyle(.white.opacity(0.78))
                .padding(.top, 12)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 28)
        .padding(.top, 36)
        .padding(.bottom, 40)
        .background(LoginStyle.brand.ignoresSafeArea(edges: .top))
    }

    // MARK: - 화이트 폼 패널

    private var panel: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("동반자 코드를 입력해주세요")
                .font(.system(size: 24, weight: .bold))
                .foregroundStyle(LoginStyle.ink)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)

            Text("보호자님께 받으신 6자리 코드를 넣어주세요.")
                .font(.system(size: 16))
                .foregroundStyle(LoginStyle.inkSoft)
                .padding(.top, 10)

            codeField
                .padding(.top, 28)

            errorRow
                .padding(.top, 12)

            submitButton
                .padding(.top, 20)

            Text("서버 · \(serverLabel)")
                .font(.system(size: 12))
                .foregroundStyle(LoginStyle.inkSoft.opacity(0.7))
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.top, 18)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 28)
        .padding(.top, 34)
        .padding(.bottom, 44)
    }

    private var codeField: some View {
        ZStack {
            // 입력은 보이지 않는 필드가 받고, 아래 칸들은 그 값을 그리기만 한다.
            TextField("", text: $code)
                .keyboardType(.asciiCapable)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
                .textContentType(.oneTimeCode)
                .focused($keyboardFocused)
                .frame(width: 1, height: 1)
                .opacity(0.01)
                .onChange(of: code) { _, newValue in handleInput(newValue) }

            HStack(spacing: 9) {
                ForEach(0 ..< length, id: \.self) { index in
                    digitBox(at: index)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { keyboardFocused = true }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("인증 코드 \(length)자리 입력")
        .accessibilityValue(code.isEmpty ? "비어 있음" : code.map(String.init).joined(separator: " "))
    }

    private func digitBox(at index: Int) -> some View {
        let characters = Array(code)
        let filled = index < characters.count
        let isActive = index == characters.count && keyboardFocused && errorText == nil

        return RoundedRectangle(cornerRadius: 10)
            .fill(LoginStyle.surface)
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(borderColor(filled: filled, active: isActive),
                            lineWidth: isActive || errorText != nil ? 2 : 1)
            )
            .frame(height: LoginStyle.boxHeight)
            .overlay(
                Text(filled ? String(characters[index]) : "")
                    .font(.system(size: 27, weight: .semibold, design: .monospaced))
                    .foregroundStyle(LoginStyle.ink)
            )
    }

    private func borderColor(filled: Bool, active: Bool) -> Color {
        if errorText != nil { return LoginStyle.danger }
        if active { return LoginStyle.brand }
        return filled ? LoginStyle.brand.opacity(0.45) : LoginStyle.stroke
    }

    private var errorRow: some View {
        Group {
            if let errorText {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.circle.fill")
                    Text(errorText)
                }
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(LoginStyle.danger)
            } else {
                Color.clear.frame(height: 20)
            }
        }
        .animation(.easeOut(duration: 0.15), value: errorText)
    }

    private var submitButton: some View {
        Button {
            submit()
        } label: {
            Text(isChecking ? "확인 중…" : "시작하기")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: LoginStyle.buttonHeight)
                .background(isComplete ? LoginStyle.brand : LoginStyle.brandMuted,
                            in: RoundedRectangle(cornerRadius: 10))
        }
        .disabled(!isComplete || isChecking)
        .animation(.easeOut(duration: 0.15), value: isComplete)
    }

    // MARK: - 동작

    private func handleInput(_ newValue: String) {
        // 영문+숫자만 받고 대문자로 통일한다 — 칸마다 글자 모양이 들쭉날쭉하면 읽기 어렵다.
        let digits = String(newValue.filter { $0.isLetter || $0.isNumber }
                                    .prefix(length)).uppercased()
        if digits != newValue { code = digits }

        if errorText != nil { errorText = nil }
        if digits.count == length {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            submit()   // 6자리를 채우면 버튼을 찾지 않아도 넘어간다
        }
    }

    private func submit() {
        guard isComplete, !isChecking else { return }
        isChecking = true
        keyboardFocused = false

        Task {
            // 서버가 코드를 기기 토큰으로 바꿔준다. nil이면 성공.
            let failure = await auth.verify(code)
            isChecking = false
            guard let failure else {
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                return
            }
            UINotificationFeedbackGenerator().notificationOccurred(.error)
            errorText = failure
            code = ""
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { keyboardFocused = true }
        }
    }
}

#Preview {
    LoginView(auth: AuthStore())
}
