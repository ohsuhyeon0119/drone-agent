import AVFoundation
import Combine
import SwiftUI

/// 소켓·오디오·카메라를 묶고 화면에 뿌릴 상태를 들고 있는 유일한 객체.
@MainActor
final class AppModel: ObservableObject {
    @Published var isLive = false
    @Published var status = "대기 중"
    @Published var caption = ""
    /// 감지기별로 따로 들고 있어야 한다 — 한 칸에 쓰면 2초마다 서로 덮어써서 읽을 수가 없다.
    /// 시나리오는 콘솔에서 늘어날 수 있으므로 종류를 앱에 박아두지 않고 키로 받는다.
    @Published var detections: [String: String] = [:]
    /// 화면 순서가 매번 뒤집히지 않도록 처음 등장한 순서를 기억한다.
    @Published private(set) var detectionOrder: [String] = []
    @Published var alertText: String?
    @Published var alertIsPositive = false
    @Published var isBusy = false

    let camera = CameraCapture()
    private let audio = AudioIO()
    private let socket = SessionClient()

    /// 자막은 조각으로 흘러온다 — turn_complete가 오면 다음 조각부터 새 문장으로 시작한다.
    private var captionClosed = true
    private var alertClearTask: Task<Void, Never>?

    init() {
        wire()
    }

    // MARK: - 화면에서 부르는 것

    /// 대화 시작 전에도 프리뷰가 보이도록 카메라만 먼저 띄운다.
    func prepareCamera() async {
        guard await CameraCapture.requestPermission() else {
            status = "카메라 권한이 거부되었습니다"
            return
        }
        camera.start()
    }

    func toggle() {
        if isLive {
            stop(reason: "종료됨")
        } else {
            Task { await start() }
        }
    }

    func flipCamera() {
        camera.flip()
    }

    /// 페어링 토큰을 소켓에 물려준다 (ContentView가 진입 시 넘긴다).
    func use(deviceToken: String) {
        socket.deviceToken = deviceToken
    }

    /// 로그아웃처럼 화면을 떠날 때 세션이 살아남지 않도록.
    func stopIfLive() {
        guard isLive else { return }
        stop(reason: "종료됨")
    }

    // MARK: - 세션

    private func start() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }

        status = "권한 확인 중…"
        guard await AudioIO.requestMicPermission() else {
            status = "마이크 권한이 거부되었습니다"
            return
        }
        guard await CameraCapture.requestPermission() else {
            status = "카메라 권한이 거부되었습니다"
            return
        }

        status = "연결 중…"
        socket.connect()

        do {
            try audio.start()
        } catch {
            status = "오디오 시작 실패: \(error.localizedDescription)"
            socket.disconnect()
            return
        }

        camera.start()
        caption = ""
        detections = [:]
        detectionOrder = []
        captionClosed = true
        isLive = true
    }

    private func stop(reason: String) {
        audio.stop()
        socket.disconnect()
        isLive = false
        status = reason
        caption = ""
    }

    // MARK: - 배선

    private func wire() {
        socket.onState = { [weak self] connected, message in
            Task { @MainActor in
                guard let self else { return }
                self.status = message
                if !connected, self.isLive {
                    self.stop(reason: message)
                }
            }
        }

        socket.onAudio = { [weak self] data in
            self?.audio.play(data)
        }

        socket.onEvent = { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }

        audio.onMicPCM = { [weak self] pcm in
            self?.socket.send(pcm: pcm)
        }

        camera.onJPEGBase64 = { [weak self] base64 in
            self?.socket.send(jpegBase64: base64)
        }
    }

    private func handle(_ event: AgentEvent) {
        switch event.type {
        case "gemini":
            if captionClosed {
                caption = ""
                captionClosed = false
            }
            caption += event.text ?? ""

        case "turn_complete":
            captionClosed = true

        case "interrupted":
            // 사용자가 끼어들었다 — 예약된 AI 음성을 즉시 버린다.
            audio.flushPlayback()
            captionClosed = true

        case "detect_result":
            // 2초마다 온다. confidence/reason까지 띄워야 왜 안 잡히는지 화면에서 알 수 있다.
            guard let source = event.source else { return }
            // 서버가 시나리오 이름(label)을 함께 준다 — 아이콘을 종류별로 박아두면
            // 콘솔에서 시나리오를 추가할 때마다 앱을 다시 배포해야 한다.
            let label = (event.raw["label"] as? String) ?? source
            let line: String
            if event.raw["ok"] as? Bool == true {
                let detected = event.raw["event"] as? String ?? "?"
                let confidence = (event.raw["confidence"] as? Double) ?? 0
                let reason = (event.raw["reason"] as? String) ?? ""
                let mark = detected == "none" ? "·" : "●"
                line = "\(mark) \(label) \(Int(confidence * 100))%  \(reason)"
            } else {
                line = "⚠ \(label): \((event.raw["error"] as? String) ?? "알 수 없음")"
            }
            if detections[source] == nil { detectionOrder.append(source) }
            detections[source] = line

        case "system_nudge":
            showAlert("▶︎ 감지 확정 — 동행이가 먼저 말을 겁니다", positive: true)

        case "memory_update":
            showAlert(event.message ?? "메모리 업데이트됨", positive: true)

        case "alert":
            showAlert(event.message ?? "알림")

        case "tool_call", "tool_result":
            if let name = event.raw["name"] as? String {
                showAlert("도구 실행: \(name)", positive: true)
            }

        case "error":
            status = "오류: " + ((event.raw["error"] as? String) ?? "알 수 없음")

        default:
            break
        }
    }

    private func showAlert(_ text: String, positive: Bool = false) {
        alertText = text
        alertIsPositive = positive
        alertClearTask?.cancel()
        alertClearTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(6))
            guard !Task.isCancelled else { return }
            await MainActor.run { self?.alertText = nil }
        }
    }
}
