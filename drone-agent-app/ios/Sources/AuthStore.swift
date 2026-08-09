import Combine
import Foundation

/// 동반자 코드로 받아온 기기 신원.
///
/// 보호자는 이메일·비밀번호로 로그인하지만 어르신 폰은 코드 하나만 넣는다.
/// 서버(`POST /api/pair`)가 코드를 기기 토큰으로 바꿔주고, 이후 모든 연결은
/// 그 토큰으로 "누구의 어르신 곁인지"를 증명한다.
@MainActor
final class AuthStore: ObservableObject {
    private enum Key {
        static let token = "deviceToken"
        static let agentId = "pairedAgentId"
        static let elderName = "pairedElderName"
        static let code = "companionAgentCode"
    }

    @Published private(set) var isAuthenticated: Bool
    @Published private(set) var token: String
    @Published private(set) var elderName: String
    @Published private(set) var code: String

    init() {
        let defaults = UserDefaults.standard
        token = defaults.string(forKey: Key.token) ?? ""
        elderName = defaults.string(forKey: Key.elderName) ?? ""
        code = defaults.string(forKey: Key.code) ?? ""
        isAuthenticated = !(defaults.string(forKey: Key.token) ?? "").isEmpty
    }

    /// 성공하면 nil, 실패하면 화면에 그대로 띄울 문구를 돌려준다.
    /// "코드가 틀림"과 "서버에 못 붙음"은 사용자가 취할 행동이 달라서 구분해야 한다.
    func verify(_ input: String) async -> String? {
        let normalized = input.uppercased()
        guard let url = Config.api("/api/pair") else {
            return "서버 주소가 올바르지 않아요"
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["code": normalized])
        request.timeoutInterval = 15

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0

            if status == 404 {
                return "코드가 맞지 않아요. 다시 확인해주세요"
            }
            guard status == 200,
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let issued = object["token"] as? String, !issued.isEmpty else {
                return "서버가 응답하지 않아요 (\(status))"
            }

            let defaults = UserDefaults.standard
            defaults.set(issued, forKey: Key.token)
            defaults.set(normalized, forKey: Key.code)
            defaults.set(object["agent_id"] as? Int ?? 0, forKey: Key.agentId)
            let name = (object["elder_name"] as? String) ?? ""
            defaults.set(name, forKey: Key.elderName)

            token = issued
            code = normalized
            elderName = name
            isAuthenticated = true
            return nil
        } catch {
            return "서버에 연결할 수 없어요. 인터넷을 확인해주세요"
        }
    }

    func signOut() {
        let defaults = UserDefaults.standard
        [Key.token, Key.agentId, Key.elderName, Key.code].forEach(defaults.removeObject(forKey:))
        token = ""
        elderName = ""
        code = ""
        isAuthenticated = false
    }
}
