import ExpoModulesCore

public final class RonnWakeWordModule: Module {
  private let engine = RonnWakeWordEngine()

  public func definition() -> ModuleDefinition {
    Name("RonnWakeWord")
    Events("onWakeWord", "onWakeWordState")

    AsyncFunction("isSupported") { () -> Bool in
      return true
    }

    AsyncFunction("isRunning") { () -> Bool in
      return self.engine.isRunning
    }

    AsyncFunction("start") { (_ keyword: String) -> Bool in
      let requested = keyword.trimmingCharacters(in: .whitespacesAndNewlines)
      try self.engine.start(keyword: requested.isEmpty ? "RONN" : requested) { [weak self] detected in
        self?.sendEvent("onWakeWord", ["keyword": detected])
      }
      self.sendEvent("onWakeWordState", ["state": "listening"])
      return true
    }.runOnQueue(.main)

    AsyncFunction("stop") { () -> Bool in
      self.engine.stop()
      self.sendEvent("onWakeWordState", ["state": "stopped"])
      return true
    }.runOnQueue(.main)

    OnDestroy {
      self.engine.stop()
    }
  }
}
