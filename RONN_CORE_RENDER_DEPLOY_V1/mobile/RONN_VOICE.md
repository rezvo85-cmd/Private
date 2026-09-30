# RONN Always Ready Voice

This mobile voice layer is input/output only. R23 remains the single RONN brain.

## What it does

1. Enable **Settings -> Always Ready** once.
2. RONN requests microphone + Apple speech-recognition permission.
3. The app continuously listens for the wake name **RONN**.
4. A phrase such as **"RONN, who is Iron Man?"** is transcribed locally/by the iOS speech service.
5. The text is sent to the existing `/api/v1/chat/complete` endpoint, so the normal R23 route, memory, tools, research, and response logic remain unchanged.
6. The returned answer is spoken through the iPhone.
7. After waking, follow-up speech is treated as part of the same conversation for about 75 seconds.
8. Say **"go to sleep"**, **"stop listening"**, or **"that's all"** to return immediately to wake-name-only mode.

## Installed native helpers

- `expo-speech-recognition@3.1.3` — SDK 55 speech recognition using Apple's `SFSpeechRecognizer` on iOS.
- `expo-speech@~55.0.18` — native text-to-speech output.
- `expo-audio@~55.0.18` — audio-session/background-audio configuration.

No second LLM, router, planner, memory store, or voice-agent brain is introduced.

## iOS build

This uses native modules, so make a development/device build rather than a plain JavaScript-only runtime:

```bash
cd RONN_CORE_RENDER_DEPLOY_V1/mobile
npm install
npx expo prebuild --platform ios --clean
npx expo run:ios
```

The existing GitHub iOS workflows also perform prebuild, CocoaPods install, and Xcode compilation.

## iOS behavior boundary

The app declares the iOS audio background mode and configures continuous recognition. iOS can still interrupt or suspend third-party audio/speech work because of phone calls, microphone ownership, power management, or other system policy. Force-closing RONN always stops listening. RONN does not claim Siri-level system privileges.

## Privacy

Always Ready is opt-in and stored only as an on-device preference. RONN stops recognition while it is thinking or speaking so its own voice is not fed back as a new command.
