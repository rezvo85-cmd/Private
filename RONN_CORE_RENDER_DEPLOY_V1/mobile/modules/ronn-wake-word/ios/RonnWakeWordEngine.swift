@preconcurrency import AVFoundation
import Foundation

final class RonnWakeWordEngine: @unchecked Sendable {
  private let audioEngine = AVAudioEngine()
  private let processingQueue = DispatchQueue(label: "ai.ronn.wakeword.processing", qos: .userInitiated)
  private var spotter: SherpaOnnxKeywordSpotterWrapper?
  private var detectionHandler: ((String) -> Void)?
  private var generation: UInt64 = 0
  private var lastDetectionAt: TimeInterval = 0

  private(set) var isRunning = false

  func start(keyword: String, onDetection: @escaping (String) -> Void) throws {
    if isRunning {
      detectionHandler = onDetection
      return
    }

    let paths = try Self.modelPaths()
    let transducer = sherpaOnnxOnlineTransducerModelConfig(
      encoder: paths.encoder,
      decoder: paths.decoder,
      joiner: paths.joiner
    )
    let model = sherpaOnnxOnlineModelConfig(
      tokens: paths.tokens,
      transducer: transducer,
      numThreads: 1,
      provider: "cpu",
      debug: 0,
      modelingUnit: "phone+ppinyin"
    )
    let feature = sherpaOnnxFeatureConfig(sampleRate: 16000, featureDim: 80)

    // RONN is pronounced like "Ron". These ARPAbet tokens are present in the
    // packaged zh-en KWS token set. The @ label is what Sherpa returns on hit.
    let keywordDefinition = "R AA1 N @RONN"
    var config = sherpaOnnxKeywordSpotterConfig(
      featConfig: feature,
      modelConfig: model,
      keywordsFile: "",
      maxActivePaths: 4,
      numTrailingBlanks: 1,
      keywordsScore: 3.0,
      keywordsThreshold: 0.18,
      keywordsBuf: keywordDefinition,
      keywordsBufSize: keywordDefinition.utf8.count
    )
    let newSpotter = SherpaOnnxKeywordSpotterWrapper(config: &config)

    let session = AVAudioSession.sharedInstance()
    try session.setCategory(
      .playAndRecord,
      mode: .measurement,
      options: [.defaultToSpeaker, .allowBluetoothHFP, .mixWithOthers]
    )
    try session.setActive(true)

    let input = audioEngine.inputNode
    let format = input.inputFormat(forBus: 0)
    guard format.channelCount > 0, format.sampleRate > 0 else {
      throw RonnWakeWordError.microphoneUnavailable
    }

    generation &+= 1
    let activeGeneration = generation
    detectionHandler = onDetection
    spotter = newSpotter
    lastDetectionAt = 0

    input.removeTap(onBus: 0)
    input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
      guard
        let self,
        activeGeneration == self.generation,
        let channel = buffer.floatChannelData?[0]
      else { return }

      let count = Int(buffer.frameLength)
      if count == 0 { return }
      let samples = Array(UnsafeBufferPointer(start: channel, count: count))
      let sampleRate = max(1, Int(buffer.format.sampleRate.rounded()))

      self.processingQueue.async { [weak self] in
        self?.consume(samples: samples, sampleRate: sampleRate, generation: activeGeneration)
      }
    }

    audioEngine.prepare()
    try audioEngine.start()
    isRunning = true
  }

  func stop() {
    guard isRunning || spotter != nil else { return }
    generation &+= 1
    isRunning = false
    audioEngine.inputNode.removeTap(onBus: 0)
    audioEngine.stop()
    spotter = nil
    detectionHandler = nil
  }

  private func consume(samples: [Float], sampleRate: Int, generation activeGeneration: UInt64) {
    guard activeGeneration == generation, isRunning, let spotter else { return }

    spotter.acceptWaveform(samples: samples, sampleRate: sampleRate)
    while spotter.isReady() {
      spotter.decode()
    }

    let result = spotter.getResult()
    let keyword = result.keyword.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !keyword.isEmpty else { return }

    let now = Date().timeIntervalSince1970
    guard now - lastDetectionAt > 1.2 else {
      spotter.reset()
      return
    }
    lastDetectionAt = now
    spotter.reset()

    let handler = detectionHandler
    DispatchQueue.main.async {
      handler?(keyword)
    }
  }

  private static func modelPaths() throws -> (encoder: String, decoder: String, joiner: String, tokens: String) {
    func path(_ name: String, _ ext: String) throws -> String {
      guard let value = Bundle.main.path(forResource: name, ofType: ext) else {
        throw RonnWakeWordError.missingModelFile("\(name).\(ext)")
      }
      return value
    }

    return (
      try path("ronn-kws-encoder", "onnx"),
      try path("ronn-kws-decoder", "onnx"),
      try path("ronn-kws-joiner", "onnx"),
      try path("ronn-kws-tokens", "txt")
    )
  }
}

enum RonnWakeWordError: LocalizedError {
  case microphoneUnavailable
  case missingModelFile(String)

  var errorDescription: String? {
    switch self {
    case .microphoneUnavailable:
      return "RONN could not access an iPhone microphone input."
    case .missingModelFile(let name):
      return "RONN wake-word model file is missing: \(name)"
    }
  }
}
