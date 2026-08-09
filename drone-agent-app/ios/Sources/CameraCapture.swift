import AVFoundation
import CoreImage
import SwiftUI

/// 카메라 프리뷰 + 초당 1장 JPEG 캡처.
///
/// 프리뷰는 앱을 켜면 바로 돌고, 프레임 전송은 소켓이 열려 있을 때만 실제로 나간다
/// (`SessionClient.send`가 isOpen으로 막는다). 그래서 "대화 시작" 전에도 화면은 보인다.
final class CameraCapture: NSObject {
    let session = AVCaptureSession()

    private let queue = DispatchQueue(label: "droneagent.camera")
    private let output = AVCaptureVideoDataOutput()
    private let ciContext = CIContext()

    private var lastSentAt = Date.distantPast
    private var position: AVCaptureDevice.Position = .back
    private var isConfigured = false

    var onJPEGBase64: ((String) -> Void)?

    static func requestPermission() async -> Bool {
        await AVCaptureDevice.requestAccess(for: .video)
    }

    func start() {
        queue.async { [self] in
            if !isConfigured {
                configure()
                isConfigured = true
            }
            if !session.isRunning { session.startRunning() }
        }
    }

    func stop() {
        queue.async { [self] in
            if session.isRunning { session.stopRunning() }
        }
    }

    func flip() {
        queue.async { [self] in
            position = (position == .back) ? .front : .back
            session.beginConfiguration()
            session.inputs.forEach { session.removeInput($0) }
            addInput()
            session.commitConfiguration()
            applyRotation()
        }
    }

    // MARK: - 구성

    private func configure() {
        session.beginConfiguration()
        // 서버 감지 루프가 쓰는 해상도와 맞춰둔다 — 더 키워도 VLM 입력에선 의미가 없다.
        session.sessionPreset = .vga640x480
        addInput()

        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }

        session.commitConfiguration()
        applyRotation()
    }

    private func addInput() {
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: position),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return }
        session.addInput(input)
    }

    private func applyRotation() {
        guard let connection = output.connection(with: .video) else { return }
        // 폰을 세로로 들고 쓰는 앱이라 버퍼를 90도 돌려야 사람이 똑바로 선 채로 모델에 들어간다.
        if connection.isVideoRotationAngleSupported(90) {
            connection.videoRotationAngle = 90
        }
        if connection.isVideoMirroringSupported {
            connection.automaticallyAdjustsVideoMirroring = false
            connection.isVideoMirrored = false
        }
    }
}

extension CameraCapture: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(_ captureOutput: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard let onJPEGBase64 else { return }

        let now = Date()
        guard now.timeIntervalSince(lastSentAt) >= Config.frameInterval else { return }
        lastSentAt = now

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let jpeg = ciContext.jpegRepresentation(
            of: image,
            colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: Config.jpegQuality]
        ) else { return }

        onJPEGBase64(jpeg.base64EncodedString())
    }
}

// MARK: - SwiftUI 프리뷰

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.videoLayer.session = session
        view.videoLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {}

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var videoLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

        override func layoutSubviews() {
            super.layoutSubviews()
            if let connection = videoLayer.connection, connection.isVideoRotationAngleSupported(90) {
                connection.videoRotationAngle = 90
            }
        }
    }
}
