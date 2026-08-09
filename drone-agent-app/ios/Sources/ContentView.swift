import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var model = AppModel()
    @EnvironmentObject private var auth: AuthStore

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
                ForEach(model.detectionOrder, id: \.self) { key in
                    if let line = model.detections[key] { chip(line) }
                }
                if !model.caption.isEmpty {
                    captionView
                }

                controls
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .preferredColorScheme(.dark)
        .animation(.easeOut(duration: 0.2), value: model.alertText)
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
        // 코드 재입력은 어르신이 실수로 누를 일이 없어야 한다 — 길게 눌러야만 풀린다.
        .onLongPressGesture(minimumDuration: 1.5) {
            model.stopIfLive()
            auth.signOut()
        }
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
