@preconcurrency import AVFoundation
import Foundation

final class RonnNeuralVoiceEngine: @unchecked Sendable {
  private let synthesisQueue = DispatchQueue(label: "ai.ronn.neuralvoice.synthesis", qos: .userInitiated)
  private let stateLock = NSLock()
  private let audioEngine = AVAudioEngine()
  private let player = AVAudioPlayerNode()
  private var tts: SherpaOnnxOfflineTtsWrapper?
  private var generation: UInt64 = 0
  private var playerAttached = false

  var isAvailable: Bool {
    return (try? Self.modelPaths()) != nil
  }

  func speak(
    text: String,
    speakerId: Int = 0,
    speed: Float = 1.05,
    completion: @escaping (Result<Void, Error>) -> Void
  ) {
    let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !clean.isEmpty else {
      completion(.success(()))
      return
    }

    let token = nextGeneration()
    synthesisQueue.async { [weak self] in
      guard let self else { return }
      do {
        let engine = try self.ensureTts()
        let sid = max(0, min(speakerId, max(0, Int(engine.numSpeakers) - 1)))
        let generated = engine.generate(text: clean, sid: sid, speed: max(0.78, min(speed, 1.28)))
        let samples = generated.samples
        let sampleRate = Int(generated.sampleRate)
        guard !samples.isEmpty, sampleRate > 0 else {
          throw RonnNeuralVoiceError.generationFailed
        }

        DispatchQueue.main.async { [weak self] in
          guard let self else { return }
          guard self.isCurrent(token) else {
            completion(.success(()))
            return
          }
          do {
            try self.play(samples: samples, sampleRate: sampleRate, token: token, completion: completion)
          } catch {
            completion(.failure(error))
          }
        }
      } catch {
        DispatchQueue.main.async {
          completion(.failure(error))
        }
      }
    }
  }

  func stop() {
    _ = nextGeneration()
    DispatchQueue.main.async { [weak self] in
      guard let self else { return }
      if self.player.isPlaying {
        self.player.stop()
      }
      self.audioEngine.stop()
      self.audioEngine.reset()
    }
  }

  private func ensureTts() throws -> SherpaOnnxOfflineTtsWrapper {
    if let tts {
      return tts
    }
    let paths = try Self.modelPaths()
    let kitten = sherpaOnnxOfflineTtsKittenModelConfig(
      model: paths.model,
      voices: paths.voices,
      tokens: paths.tokens,
      dataDir: paths.dataDir,
      lengthScale: 1.0
    )
    var config = sherpaOnnxOfflineTtsConfig(
      model: sherpaOnnxOfflineTtsModelConfig(
        numThreads: 2,
        debug: 0,
        provider: "cpu",
        kitten: kitten
      ),
      maxNumSentences: 1,
      silenceScale: 0.16
    )
    let created = withUnsafePointer(to: &config) { ptr in
      SherpaOnnxOfflineTtsWrapper(config: ptr)
    }
    guard created.tts != nil else {
      throw RonnNeuralVoiceError.initializationFailed
    }
    tts = created
    return created
  }

  private func play(
    samples: [Float],
    sampleRate: Int,
    token: UInt64,
    completion: @escaping (Result<Void, Error>) -> Void
  ) throws {
    let session = AVAudioSession.sharedInstance()
    try session.setCategory(
      .playAndRecord,
      mode: .voiceChat,
      options: [.defaultToSpeaker, .allowBluetoothHFP, .duckOthers]
    )
    try session.setActive(true)

    guard let format = AVAudioFormat(
      commonFormat: .pcmFormatFloat32,
      sampleRate: Double(sampleRate),
      channels: 1,
      interleaved: false
    ) else {
      throw RonnNeuralVoiceError.audioFormatFailed
    }

    if !playerAttached {
      audioEngine.attach(player)
      playerAttached = true
    } else {
      audioEngine.disconnectNodeOutput(player)
    }
    audioEngine.connect(player, to: audioEngine.mainMixerNode, format: format)

    guard let buffer = AVAudioPCMBuffer(
      pcmFormat: format,
      frameCapacity: AVAudioFrameCount(samples.count)
    ) else {
      throw RonnNeuralVoiceError.audioBufferFailed
    }
    buffer.frameLength = AVAudioFrameCount(samples.count)
    guard let channel = buffer.floatChannelData?[0] else {
      throw RonnNeuralVoiceError.audioBufferFailed
    }
    samples.withUnsafeBufferPointer { source in
      guard let base = source.baseAddress else { return }
      channel.update(from: base, count: samples.count)
    }

    audioEngine.prepare()
    if !audioEngine.isRunning {
      try audioEngine.start()
    }

    player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
      DispatchQueue.main.async {
        guard let self else { return }
        if self.isCurrent(token) {
          completion(.success(()))
        } else {
          completion(.success(()))
        }
      }
    }
    player.play()
  }

  private func nextGeneration() -> UInt64 {
    stateLock.lock()
    generation &+= 1
    let value = generation
    stateLock.unlock()
    return value
  }

  private func isCurrent(_ token: UInt64) -> Bool {
    stateLock.lock()
    let current = generation == token
    stateLock.unlock()
    return current
  }

  private static func modelPaths() throws -> (model: String, voices: String, tokens: String, dataDir: String) {
    func file(_ name: String, _ ext: String) throws -> String {
      guard let value = Bundle.main.path(forResource: name, ofType: ext) else {
        throw RonnNeuralVoiceError.missingModelFile("\(name).\(ext)")
      }
      return value
    }
    guard let dataDir = Bundle.main.path(forResource: "ronn-tts-espeak-ng-data", ofType: nil) else {
      throw RonnNeuralVoiceError.missingModelFile("ronn-tts-espeak-ng-data")
    }
    return (
      try file("ronn-tts-model", "onnx"),
      try file("ronn-tts-voices", "bin"),
      try file("ronn-tts-tokens", "txt"),
      dataDir
    )
  }
}

enum RonnNeuralVoiceError: LocalizedError {
  case missingModelFile(String)
  case initializationFailed
  case generationFailed
  case audioFormatFailed
  case audioBufferFailed

  var errorDescription: String? {
    switch self {
    case .missingModelFile(let name):
      return "RONN neural voice model file is missing: \(name)"
    case .initializationFailed:
      return "RONN neural voice could not initialize."
    case .generationFailed:
      return "RONN neural voice could not generate audio."
    case .audioFormatFailed:
      return "RONN neural voice audio format is unavailable."
    case .audioBufferFailed:
      return "RONN neural voice audio buffer could not be created."
    }
  }
}
