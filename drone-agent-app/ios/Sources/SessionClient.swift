import Foundation

/// 서버가 JSON으로 보내는 이벤트. 타입별 필드가 제각각이라 raw dict을 들고 다닌다.
struct AgentEvent {
    let type: String
    let raw: [String: Any]

    var text: String? { raw["text"] as? String }
    var message: String? { raw["message"] as? String }
    var source: String? { raw["source"] as? String }
}

/// `/ws/unified` 세션 하나를 관리한다.
///
/// 프로토콜 (main.py `_receive_from_client` / `_run_gemini_session` 참고):
///   앱 → 서버   binary : 16kHz PCM16 마이크 청크
///   앱 → 서버   text   : {"type":"image","mime_type":"image/jpeg","data":"<base64>"}
///   서버 → 앱   binary : 24kHz PCM16 AI 음성
///   서버 → 앱   text   : {"type": "gemini"|"user"|"detect_result"|"alert"|... }
final class SessionClient: NSObject {
    private var task: URLSessionWebSocketTask?
    private lazy var urlSession = URLSession(configuration: .default, delegate: self, delegateQueue: nil)

    private(set) var isOpen = false
    private var closeReported = false

    var onAudio: ((Data) -> Void)?
    var onEvent: ((AgentEvent) -> Void)?
    /// (연결됨 여부, 사람이 읽을 상태 문구)
    var onState: ((Bool, String) -> Void)?

    /// 페어링으로 받은 기기 토큰. 서버가 이걸로 agent_id를 판별한다.
    var deviceToken: String?

    func connect() {
        disconnect()
        closeReported = false
        guard let url = Config.unifiedURL(token: deviceToken) else {
            onState?(false, "서버 주소가 올바르지 않습니다")
            return
        }
        let t = urlSession.webSocketTask(with: url)
        task = t
        t.resume()
        receive()
    }

    func disconnect() {
        isOpen = false
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
    }

    func send(pcm: Data) {
        guard isOpen, let task else { return }
        task.send(.data(pcm)) { [weak self] error in
            if let error { self?.reportClosed("오디오 전송 실패: \(error.localizedDescription)") }
        }
    }

    func send(jpegBase64: String) {
        guard isOpen, let task else { return }
        let payload: [String: Any] = [
            "type": "image",
            "mime_type": "image/jpeg",
            "data": jpegBase64,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let string = String(data: data, encoding: .utf8) else { return }
        task.send(.string(string)) { _ in }
    }

    /// JSON이 아닌 평문은 서버가 그대로 텍스트 입력으로 넘긴다.
    func send(text: String) {
        guard isOpen, let task else { return }
        task.send(.string(text)) { _ in }
    }

    private func receive() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error):
                self.reportClosed("연결 끊김: \(error.localizedDescription)")
            case .success(let message):
                switch message {
                case .data(let data):
                    self.onAudio?(data)
                case .string(let string):
                    self.handle(string)
                @unknown default:
                    break
                }
                self.receive()
            }
        }
    }

    private func handle(_ string: String) {
        guard let data = string.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String else { return }
        onEvent?(AgentEvent(type: type, raw: object))
    }

    private func reportClosed(_ message: String) {
        guard !closeReported else { return }
        closeReported = true
        isOpen = false
        onState?(false, message)
    }
}

extension SessionClient: URLSessionWebSocketDelegate {
    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        isOpen = true
        onState?(true, "연결됨")
    }

    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
                    reason: Data?) {
        reportClosed("서버가 연결을 닫음 (\(closeCode.rawValue))")
    }
}
