import AVFoundation

/// 마이크 캡처(→16kHz PCM16)와 AI 음성 재생(24kHz PCM16)을 한 엔진에서 처리한다.
///
/// 핵심은 voice processing(AEC)이다. 스피커로 나간 동행이 목소리를 마이크가 되받으면
/// 모델이 제 말에 반응해서 대화가 무너지는데, iOS의 VPIO 유닛이 이걸 하드웨어에서 잡는다.
/// 브라우저 버전에는 없는 이점이라 반드시 켠 상태로 데모할 것.
final class AudioIO {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let ioQueue = DispatchQueue(label: "droneagent.audio")

    private let playFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                           sampleRate: Config.playSampleRate,
                                           channels: 1,
                                           interleaved: false)!

    private let micFormat = AVAudioFormat(commonFormat: .pcmFormatInt16,
                                          sampleRate: Config.micSampleRate,
                                          channels: 1,
                                          interleaved: true)!

    private var converter: AVAudioConverter?
    private var isTapped = false
    private var isAttached = false

    // 진단용 — 마이크가 안 잡힐 때 "탭이 안 불리는지 / 변환이 깨지는지 / 소켓이 안 받는지"를
    // 화면 없이 구분할 방법이 없었다.
    private var tapCallbacks = 0
    private var sentChunks = 0
    private var sentBytes = 0
    private var conversionErrors = 0
    private var emptyOutputs = 0

    /// 변환된 16kHz PCM16 청크. 오디오 스레드에서 불린다.
    var onMicPCM: ((Data) -> Void)?

    static func requestMicPermission() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
    }

    // MARK: - 수명주기

    func start() throws {
        try startEngine(voiceProcessing: true)

        // start()가 예외 없이 돌아왔는데도 엔진이 안 도는 경우가 있다. VPIO 유닛이
        // 붙는 과정에서 세션이 한 번 재구성되기 때문인데, 이때는 조용히 실패해서
        // "연결은 됐는데 마이크만 안 잡히는" 상태가 된다. AEC를 포기하고 다시 띄운다.
        if !engine.isRunning {
            log("⚠️ AEC 켠 상태로 엔진이 뜨지 않음 — AEC 끄고 재시도")
            teardownGraph()
            try startEngine(voiceProcessing: false)
        }

        guard engine.isRunning else {
            throw NSError(domain: "AudioIO", code: -2, userInfo: [
                NSLocalizedDescriptionKey: "오디오 엔진을 시작하지 못했습니다",
            ])
        }
    }

    private func startEngine(voiceProcessing: Bool) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord,
                                mode: .voiceChat,
                                options: [.defaultToSpeaker, .allowBluetooth])

        let input = engine.inputNode

        // AEC는 engine.start() 전에, 그리고 입력 포맷을 읽기 전에 켜야 한다 —
        // 켜는 순간 inputNode의 포맷이 바뀐다. 출력 노드에는 걸지 않는다(같은 VPIO
        // 유닛을 두 번 건드리면 그래프가 어긋난다).
        do {
            try input.setVoiceProcessingEnabled(voiceProcessing)
            log(voiceProcessing ? "voice processing 켬 (AEC)" : "voice processing 끔")
        } catch {
            log("⚠️ voice processing \(voiceProcessing) 설정 실패: \(error.localizedDescription)")
        }

        // 세션 활성화는 VP를 켠 다음이어야 한다. 먼저 활성화하면 VP가 세션을
        // 재구성하면서 비활성으로 떨어뜨리고, 그 뒤 engine.start()는 조용히 실패한다.
        try session.setActive(true)

        if !isAttached {
            engine.attach(player)
            isAttached = true
        }
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)

        let hardwareFormat = input.outputFormat(forBus: 0)
        guard hardwareFormat.sampleRate > 0 else {
            throw NSError(domain: "AudioIO", code: -1, userInfo: [
                NSLocalizedDescriptionKey: "마이크 입력 포맷을 읽지 못했습니다 (권한이나 세션 설정 확인)",
            ])
        }

        // 리샘플러는 상태를 갖는다 — 탭 콜백마다 새로 만들면 경계에서 잡음이 낀다.
        converter = AVAudioConverter(from: hardwareFormat, to: micFormat)

        if !isTapped {
            input.installTap(onBus: 0, bufferSize: 2048, format: hardwareFormat) { [weak self] buffer, _ in
                self?.pushMic(buffer)
            }
            isTapped = true
        }

        engine.prepare()
        try engine.start()
        player.play()

        log("입력 \(hardwareFormat.sampleRate)Hz ch\(hardwareFormat.channelCount) "
            + "→ \(micFormat.sampleRate)Hz / 세션 \(session.sampleRate)Hz "
            + "/ 입력가능 \(session.isInputAvailable) / 엔진 \(engine.isRunning)")
    }

    private func teardownGraph() {
        if isTapped {
            engine.inputNode.removeTap(onBus: 0)
            isTapped = false
        }
        player.stop()
        engine.stop()
        engine.reset()
        converter = nil
    }

    private func log(_ message: String) {
        NSLog("[AudioIO] %@", message)
    }

    func stop() {
        teardownGraph()
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    // MARK: - 마이크 → 16kHz PCM16

    private func pushMic(_ buffer: AVAudioPCMBuffer) {
        tapCallbacks += 1
        if tapCallbacks == 1 {
            log("탭 첫 호출: \(buffer.frameLength)프레임 @\(buffer.format.sampleRate)Hz")
        }
        guard let converter else { log("⚠️ converter 없음"); return }
        guard let onMicPCM else { log("⚠️ onMicPCM 핸들러 미연결"); return }

        let ratio = micFormat.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 64
        guard let output = AVAudioPCMBuffer(pcmFormat: micFormat, frameCapacity: capacity) else { return }

        var consumed = false
        var error: NSError?
        converter.convert(to: output, error: &error) { _, status in
            if consumed {
                status.pointee = .noDataNow
                return nil
            }
            consumed = true
            status.pointee = .haveData
            return buffer
        }

        if let error {
            if conversionErrors == 0 { log("⚠️ 변환 실패: \(error.localizedDescription)") }
            conversionErrors += 1
            return
        }
        guard output.frameLength > 0, let channel = output.int16ChannelData else {
            if emptyOutputs == 0 { log("⚠️ 변환 결과가 비어 있음 (capacity \(output.frameCapacity))") }
            emptyOutputs += 1
            return
        }

        let data = Data(bytes: channel[0], count: Int(output.frameLength) * MemoryLayout<Int16>.size)
        sentChunks += 1
        sentBytes += data.count
        if sentChunks % 100 == 0 {
            log("마이크 송출 \(sentChunks)청크 / \(sentBytes)바이트 "
                + "(탭 \(tapCallbacks) · 변환실패 \(conversionErrors) · 빈결과 \(emptyOutputs))")
        }
        onMicPCM(data)
    }

    // MARK: - 24kHz PCM16 → 스피커

    /// 도착한 조각을 곧바로 재생 예약하면 네트워크 지터가 그대로 소리 구멍이 된다.
    /// 조금 모았다가(프라임) 일정 크기로 잘라 넣어, 잠깐 늦게 오는 조각을 흡수한다.
    /// 대가는 시작 지연 \(primeMilliseconds)ms인데, 끊기는 것보다 낫다.
    private let primeMilliseconds = 220
    private let chunkMilliseconds = 80

    private var pending = Data()
    private var isPriming = true
    private var scheduledChunks = 0

    private var primeBytes: Int { bytes(forMilliseconds: primeMilliseconds) }
    private var chunkBytes: Int { bytes(forMilliseconds: chunkMilliseconds) }

    private func bytes(forMilliseconds ms: Int) -> Int {
        // 16비트 mono라 프레임당 2바이트
        Int(Config.playSampleRate) * 2 * ms / 1000
    }

    func play(_ data: Data) {
        ioQueue.async { [weak self] in
            guard let self, self.engine.isRunning else { return }
            self.pending.append(data)

            // 말이 시작될 때만 모은다. 한 번 흐르기 시작하면 계속 이어 붙인다.
            if self.isPriming {
                guard self.pending.count >= self.primeBytes else { return }
                self.isPriming = false
            }
            self.drain(chunkSize: self.chunkBytes)
        }
    }

    /// 한 턴이 끝나면 남은 꼬리를 마저 내보낸다. 안 그러면 마지막 한 음절이 잘린다.
    func endOfTurn() {
        ioQueue.async { [weak self] in
            guard let self else { return }
            self.drain(chunkSize: 1)
            self.isPriming = true
        }
    }

    private func drain(chunkSize: Int) {
        while pending.count >= chunkSize, pending.count > 0 {
            let size = min(chunkBytes, pending.count)
            let chunk = pending.prefix(size)
            pending.removeFirst(size)
            schedule(Data(chunk))
        }
    }

    private func schedule(_ data: Data) {
        let frames = data.count / MemoryLayout<Int16>.size
        guard frames > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: playFormat,
                                            frameCapacity: AVAudioFrameCount(frames)) else { return }
        buffer.frameLength = AVAudioFrameCount(frames)

        // Data가 정렬돼 있다는 보장이 없어 배열로 한 번 복사한 뒤 변환한다.
        var pcm = [Int16](repeating: 0, count: frames)
        _ = pcm.withUnsafeMutableBytes { data.copyBytes(to: $0, from: 0 ..< frames * MemoryLayout<Int16>.size) }

        let destination = buffer.floatChannelData![0]
        for i in 0 ..< frames {
            destination[i] = Float(pcm[i]) / 32768.0
        }

        scheduledChunks += 1
        player.scheduleBuffer(buffer) { [weak self] in
            guard let self else { return }
            self.ioQueue.async {
                self.scheduledChunks -= 1
                // 예약이 다 소진되면 다음 말은 처음부터 다시 모은다.
                if self.scheduledChunks == 0 && self.pending.isEmpty {
                    self.isPriming = true
                }
            }
        }
        if !player.isPlaying { player.play() }
    }

    /// 사용자가 말을 끊었을 때(서버의 `interrupted` 이벤트) 이미 예약된 AI 음성을 버린다.
    /// 이게 없으면 끼어들어도 하던 말을 끝까지 다 하고 나서야 반응한다.
    func flushPlayback() {
        ioQueue.async { [weak self] in
            guard let self, self.engine.isRunning else { return }
            self.pending.removeAll()
            self.scheduledChunks = 0
            self.isPriming = true
            self.player.stop()
            self.player.play()
        }
    }
}
