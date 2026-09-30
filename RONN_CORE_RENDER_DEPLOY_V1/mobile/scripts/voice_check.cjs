const fs=require("fs");
const path=require("path");

const root=path.resolve(__dirname,"..");
const read=(p)=>fs.readFileSync(path.join(root,p),"utf8");
const fail=(m)=>{throw new Error("[RONN_VOICE] "+m)};
const expect=(ok,m)=>{if(!ok)fail(m)};

const pkg=JSON.parse(read("package.json"));
for(const dep of ["expo-audio","expo-speech","expo-speech-recognition","expo-secure-store"]){
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
expect(voice.includes('ExpoSpeechRecognitionModule.start'),"speech recognition start path missing");
expect(voice.includes('Speech.speak'),"text-to-speech path missing");
expect(voice.includes('speechReadyText'),"spoken-answer cleanup missing");
expect(voice.includes('getAvailableVoicesAsync'),"enhanced voice selection missing");

console.log("RONN_VOICE static checks passed.");
