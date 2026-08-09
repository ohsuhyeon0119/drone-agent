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

    /// 카메라 위에 겹쳐 보여줄 기록. 평소에는 화면을 가리지 않도록 감춰두고
    /// 버튼을 눌렀을 때만 반투명으로 띄운다.
    struct LogLine: Identifiable {
        let id = UUID()
        let time: String
        let text: String
        let emphasized: Bool
    }
    @Published private(set) var logLines: [LogLine] = []

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
        logLines = []
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
            audio.endOfTurn()
            if let line = caption.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty {
                appendLog("동행이: \(line)")
            }

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
            // 감지되지 않은 판정까지 기록에 쌓으면 정작 잡힌 순간이 묻힌다.
            if (event.raw["event"] as? String).map({ $0 != "none" }) == true {
                appendLog(line, emphasized: true)
            }

        case "system_nudge":
            showAlert("▶︎ 감지 확정 — 동행이가 먼저 말을 겁니다", positive: true)
            appendLog("▶︎ 감지 확정 — 동행이가 먼저 말을 겁니다", emphasized: true)

        case "memory_update":
            showAlert(event.message ?? "메모리 업데이트됨", positive: true)
            appendLog(event.message ?? "기록 남김", emphasized: true)

        case "alert":
            showAlert(event.message ?? "알림")
            appendLog("🚨 \(event.message ?? "알림")", emphasized: true)

        case "tool_call", "tool_result":
            if let name = event.raw["name"] as? String {
                showAlert("도구 실행: \(name)", positive: true)
                appendLog("행동 실행 · \(name)", emphasized: true)
            }

        case "error":
            let text = (event.raw["error"] as? String) ?? "알 수 없음"
            status = "오류: " + text
            appendLog("오류: \(text)", emphasized: true)

        default:
            break
        }
    }

    private static let clock: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private func appendLog(_ text: String, emphasized: Bool = false) {
        logLines.append(LogLine(time: Self.clock.string(from: Date()),
                                text: text, emphasized: emphasized))
        // 오래 켜두는 화면이라 무한히 쌓이면 메모리와 스크롤 둘 다 감당이 안 된다.
        if logLines.count > 120 { logLines.removeFirst(logLines.count - 120) }
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

private extension String {
    /// 빈 문자열을 nil로 — 공백뿐인 자막을 기록에 남기지 않기 위함.
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
