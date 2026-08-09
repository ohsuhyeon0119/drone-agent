import SwiftUI

/// 코드 인증 여부에 따라 로그인 화면과 대화 화면을 갈라준다.
struct RootView: View {
    @StateObject private var auth = AuthStore()

    var body: some View {
        Group {
            if auth.isAuthenticated {
                ContentView()
                    .environmentObject(auth)
                    .transition(.opacity)
            } else {
                LoginView(auth: auth)
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.25), value: auth.isAuthenticated)
    }
}
