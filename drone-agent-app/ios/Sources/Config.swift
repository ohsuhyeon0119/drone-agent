import Foundation

/// 서버 주소와 스트림 파라미터.
///
/// 주소는 앱 안에서 바꿀 수 있다 — 데모 중에 클라우드와 맥북 로컬 서버를 오가야 하는데,
/// 그때마다 재빌드하면 현장에서 대응이 안 된다. 로그인 화면의 `DRONEAGENT`를 길게 누르면
/// 입력창이 열린다.
enum Config {
    static let defaultServerBase = "https://droneagent.cloud"

    private static let overrideKey = "serverBaseOverride"

    /// 항상 http(s):// 형태로 들고 있고, WebSocket 주소는 여기서 변환해 만든다.
    static var serverBase: String {
        get { UserDefaults.standard.string(forKey: overrideKey) ?? defaultServerBase }
        set {
            var trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            while trimmed.hasSuffix("/") { trimmed.removeLast() }
            if trimmed.isEmpty || trimmed == defaultServerBase {
                UserDefaults.standard.removeObject(forKey: overrideKey)
            } else {
                UserDefaults.standard.set(trimmed, forKey: overrideKey)
            }
        }
    }

    static var isUsingDefaultServer: Bool {
        UserDefaults.standard.string(forKey: overrideKey) == nil
    }

    /// 화면에 표시할 짧은 이름 (호스트만).
    static var serverLabel: String {
        URL(string: serverBase)?.host.map { host in
            (URL(string: serverBase)?.port).map { "\(host):\($0)" } ?? host
        } ?? serverBase
    }

    static func api(_ path: String) -> URL? {
        URL(string: serverBase + path)
    }

    private static var wsBase: String {
        if serverBase.hasPrefix("https://") {
            return "wss://" + serverBase.dropFirst("https://".count)
        }
        if serverBase.hasPrefix("http://") {
            return "ws://" + serverBase.dropFirst("http://".count)
        }
        return serverBase
    }

    /// 기기 토큰을 붙여 "누구의 어르신 곁인지"를 서버에 증명한다.
    /// 토큰이 없으면 서버는 기본 에이전트로 떨어뜨린다(서명 없는 접속으로 로그에 남는다).
    static func unifiedURL(token: String?) -> URL? {
        var string = wsBase + "/ws/unified"
        if let token, !token.isEmpty,
           let escaped = token.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            string += "?token=" + escaped
        }
        return URL(string: string)
    }

    /// 서버(`_receive_from_client`)가 기대하는 마이크 포맷: 16kHz mono PCM16 raw.
    static let micSampleRate: Double = 16_000

    /// Gemini Live가 내보내는 출력 포맷: 24kHz mono PCM16 raw.
    static let playSampleRate: Double = 24_000

    /// 웹 클라이언트와 동일하게 초당 1장. 감지 루프가 2초마다 도니 이 이상은 낭비다.
    static let frameInterval: TimeInterval = 1.0

    static let jpegQuality: Double = 0.7

    /// 동반자 코드 자릿수. 서버가 헷갈리는 글자(I/1/L, O/0)를 뺀 31자 알파벳으로 만든다.
    static let accessCodeLength = 6
}
