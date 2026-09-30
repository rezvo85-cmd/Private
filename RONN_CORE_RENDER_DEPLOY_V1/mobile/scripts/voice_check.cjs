const fs=require("fs");
const path=require("path");

const root=path.resolve(__dirname,"..");
const read=(p)=>fs.readFileSync(path.join(root,p),"utf8");
const fail=(m)=>{throw new Error("[RONN_VOICE] "+m)};
const expect=(ok,m)=>{if(!ok)fail(m)};

const pkg=JSON.parse(read("package.json"));
for(const dep of ["expo-audio","expo-speech","expo-speech-recognition","expo-secure-store","ronn-wake-word"]){
  expect(pkg.dependencies&&pkg.dependencies[dep],`missing dependency: ${dep}`);
}

const app=JSON.parse(read("app.json"));
const modes=app?.expo?.ios?.infoPlist?.UIBackgroundModes||[];
expect(modes.includes("audio"),"iOS UIBackgroundModes must include audio");

const plugins=(app?.expo?.plugins||[]).map(p=>Array.isArray(p)?p[0]:p);
expect(plugins.includes("expo-speech-recognition"),"expo-speech-recognition plugin missing");
expect(plugins.includes("expo-audio"),"expo-audio plugin missing");

const appJs=read("App.js");
const voice=read("voice_mode.js");
expect(appJs.includes('useRonnVoice'),"App.js is not wired to useRonnVoice");
expect(appJs.includes('/chat/complete'),"App.js is not wired to the existing R23 chat route");
expect(appJs.includes('/chat/sse'),"voice streaming is not wired to the existing R23 SSE route");
expect(appJs.includes('expo/fetch'),"Expo streaming fetch is not enabled");
expect(voice.includes('ExpoSpeechRecognitionModule.start'),"speech recognition start path missing");
expect(voice.includes('Speech.speak'),"text-to-speech path missing");
expect(voice.includes('speechReadyText'),"spoken-answer cleanup missing");
expect(voice.includes('getAvailableVoicesAsync'),"enhanced voice selection missing");
expect(voice.includes('splitStreamSentences'),"streaming sentence splitter missing");
expect(voice.includes('handleToken'),"voice token streaming handler missing");
expect(voice.includes('supportsOnDeviceRecognition'),"on-device recognition capability check missing");
expect(voice.includes('interruptWithTranscript'),"barge-in interruption handler missing");
expect(voice.includes('cancelRonnRef'),"voice cancellation hook missing");
expect(voice.includes('startWakeWord("RONN"'),"native RONN wake-word start path missing");
expect(voice.includes('stopWakeWord'),"native RONN wake-word stop path missing");
expect(voice.includes('startNativeWake'),"native wake-word state-machine integration missing");
expect(voice.includes('CONVERSATION_TIMEOUT_MS=18000'),"follow-up window was not shortened");
expect(voice.includes('END_OF_TURN_MS=480'),"fast end-of-turn target missing");
expect(voice.includes('looksSemanticallyComplete'),"semantic turn detector missing");
expect(voice.includes('scheduleSemanticCommit'),"early semantic commit path missing");
expect(voice.includes('[RONN_VOICE_LATENCY]'),"voice latency telemetry missing");
expect(voice.includes('FIRST_STREAM_FLUSH_CHARS'),"early speech streaming flush missing");
expect(appJs.includes('AbortController'),"voice stream cancellation is not wired");
expect(appJs.includes('cancelVoiceQuery'),"voice cancellation callback missing");

console.log("RONN_VOICE static checks passed.");
