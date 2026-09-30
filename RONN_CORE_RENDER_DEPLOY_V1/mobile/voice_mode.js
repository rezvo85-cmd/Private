import {useEffect, useRef, useState} from "react";
import * as SecureStore from "expo-secure-store";
import * as Speech from "expo-speech";
import {setAudioModeAsync} from "expo-audio";
import {
  ExpoSpeechRecognitionModule,
  useSpeechRecognitionEvent,
} from "expo-speech-recognition";

const VOICE_PREF_KEY="ronn_voice_always_ready";
const CONVERSATION_TIMEOUT_MS=75000;
const WAKE_WORD_RE=/\b(?:ronn|ron)\b/i;
const SLEEP_RE=/^\s*(?:go to sleep|sleep|stop listening|that's all|that is all|never ?mind)\s*[.!?]*\s*$/i;

function normalize(text=""){
  return String(text).trim().replace(/\s+/g," ").toLowerCase();
}

function extractWakeQuery(text=""){
  const raw=String(text).trim();
  const match=WAKE_WORD_RE.exec(raw);
  if(!match)return null;
  const query=raw.slice((match.index||0)+match[0].length)
    .replace(/^[\s,.:;!?\-–—]+/,"")
    .trim();
  return {query};
}

export function useRonnVoice({askRonn}){
  const [enabled,setEnabledState]=useState(false);
  const [state,setState]=useState("off");
  const [heard,setHeard]=useState("");
  const [voiceError,setVoiceError]=useState("");

  const enabledRef=useRef(false);
  const listeningRef=useRef(false);
  const busyRef=useRef(false);
  const conversationRef=useRef(false);
  const restartTimerRef=useRef(null);
  const conversationTimerRef=useRef(null);
  const lastFinalRef=useRef("");
  const lastFinalAtRef=useRef(0);
  const askRonnRef=useRef(askRonn);

  useEffect(()=>{askRonnRef.current=askRonn},[askRonn]);

  function clearRestart(){
    if(restartTimerRef.current){
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current=null;
    }
  }

  function clearConversationTimer(){
    if(conversationTimerRef.current){
      clearTimeout(conversationTimerRef.current);
      conversationTimerRef.current=null;
    }
  }

  function armConversationTimeout(){
    clearConversationTimer();
    conversationTimerRef.current=setTimeout(()=>{
      conversationRef.current=false;
      if(enabledRef.current&&!busyRef.current){
        setState(listeningRef.current?"listening":"starting");
        scheduleRestart(100);
      }
    },CONVERSATION_TIMEOUT_MS);
  }

  async function configureAudio(){
    try{
      await setAudioModeAsync({
        allowsRecording:true,
        playsInSilentMode:true,
        allowsBackgroundRecording:true,
        shouldPlayInBackground:true,
        interruptionMode:"duckOthers",
        shouldRouteThroughEarpiece:false,
      });
    }catch{}
  }

  async function startRecognition(){
    if(!enabledRef.current||busyRef.current||listeningRef.current)return;
    clearRestart();
    try{
      const permission=await ExpoSpeechRecognitionModule.getPermissionsAsync();
      if(!permission?.granted){
        setState("permission");
        setVoiceError("Microphone and speech recognition permission are required.");
        return;
      }
      await configureAudio();
      setVoiceError("");
      setState(conversationRef.current?"awake":"starting");
      ExpoSpeechRecognitionModule.start({
        lang:"en-US",
        interimResults:true,
        continuous:true,
        maxAlternatives:1,
        contextualStrings:["RONN","Ronn","Ron"],
        requiresOnDeviceRecognition:false,
        addsPunctuation:true,
        iosTaskHint:"search",
        iosCategory:{
          category:"playAndRecord",
          categoryOptions:["defaultToSpeaker","allowBluetooth"],
          mode:"measurement",
        },
        iosVoiceProcessingEnabled:true,
      });
    }catch(e){
      setState("error");
      setVoiceError(e?.message||"RONN could not start listening.");
      scheduleRestart(1200);
    }
  }

  function scheduleRestart(delay=300){
    if(!enabledRef.current||busyRef.current)return;
    clearRestart();
    restartTimerRef.current=setTimeout(()=>{startRecognition()},delay);
  }

  async function stopRecognition(){
    clearRestart();
    try{ExpoSpeechRecognitionModule.abort()}catch{}
    listeningRef.current=false;
  }

  function finishSpeaking(){
    busyRef.current=false;
    if(!enabledRef.current){
      setState("off");
      return;
    }
    setState(conversationRef.current?"awake":"listening");
    scheduleRestart(250);
  }

  async function speak(text){
    const words=String(text||"").trim();
    if(!words){
      finishSpeaking();
      return;
    }
    await configureAudio();
    setState("speaking");
    try{Speech.stop()}catch{}
    await new Promise(resolve=>{
      let settled=false;
      const done=()=>{
        if(settled)return;
        settled=true;
        resolve();
      };
      try{
        Speech.speak(words,{
          language:"en-US",
          rate:0.93,
          pitch:0.94,
          onDone:done,
          onStopped:done,
          onError:done,
        });
      }catch{
        done();
      }
      setTimeout(done,Math.min(45000,Math.max(5000,words.length*75)));
    });
  }

  async function acknowledgeWake(){
    if(busyRef.current)return;
    busyRef.current=true;
    await stopRecognition();
    conversationRef.current=true;
    armConversationTimeout();
    await speak("Yes?");
    finishSpeaking();
  }

  async function goToSleep(){
    if(busyRef.current)return;
    busyRef.current=true;
    await stopRecognition();
    conversationRef.current=false;
    clearConversationTimer();
    await speak("Okay.");
    finishSpeaking();
  }

  async function runQuery(query){
    const q=String(query||"").trim();
    if(!q||busyRef.current)return;
    busyRef.current=true;
    await stopRecognition();
    conversationRef.current=true;
    armConversationTimeout();
    setState("thinking");
    setVoiceError("");
    try{
      const answer=await askRonnRef.current?.(q);
      if(answer){
        await speak(answer);
      }else{
        await speak("I couldn't get an answer right now.");
      }
    }catch(e){
      setVoiceError(e?.message||"RONN could not answer.");
      await speak("I couldn't reach RONN right now.");
    }finally{
      finishSpeaking();
    }
  }

  async function handleFinalTranscript(transcript){
    const raw=String(transcript||"").trim();
    if(!raw||busyRef.current)return;
    const normalized=normalize(raw);
    const now=Date.now();
    if(normalized===lastFinalRef.current&&now-lastFinalAtRef.current<2200)return;
    lastFinalRef.current=normalized;
    lastFinalAtRef.current=now;

    if(conversationRef.current){
      if(SLEEP_RE.test(raw)){
        await goToSleep();
        return;
      }
      await runQuery(raw);
      return;
    }

    const wake=extractWakeQuery(raw);
    if(!wake)return;
    if(!wake.query){
      await acknowledgeWake();
      return;
    }
    if(SLEEP_RE.test(wake.query)){
      await goToSleep();
      return;
    }
    await runQuery(wake.query);
  }

  useSpeechRecognitionEvent("start",()=>{
    listeningRef.current=true;
    setState(conversationRef.current?"awake":"listening");
    setVoiceError("");
  });

  useSpeechRecognitionEvent("end",()=>{
    listeningRef.current=false;
    if(enabledRef.current&&!busyRef.current){
      setState(conversationRef.current?"awake":"starting");
      scheduleRestart(250);
    }
  });

  useSpeechRecognitionEvent("result",(event)=>{
    const transcript=event?.results?.[0]?.transcript||"";
    if(transcript)setHeard(transcript);
    if(event?.isFinal&&transcript){
      handleFinalTranscript(transcript);
    }
  });

  useSpeechRecognitionEvent("error",(event)=>{
    listeningRef.current=false;
    const code=String(event?.error||"");
    if(!["aborted","no-speech"].includes(code)){
      setVoiceError(event?.message||code||"Speech recognition stopped.");
    }
    if(enabledRef.current&&!busyRef.current)scheduleRestart(code==="not-allowed"?1800:500);
  });

  async function setEnabled(next){
    const value=!!next;
    setVoiceError("");
    if(value){
      try{
        const permission=await ExpoSpeechRecognitionModule.requestPermissionsAsync();
        if(!permission?.granted){
          enabledRef.current=false;
          setEnabledState(false);
          setState("permission");
          setVoiceError("Enable microphone and speech recognition access for RONN.");
          await SecureStore.deleteItemAsync(VOICE_PREF_KEY);
          return false;
        }
        await configureAudio();
        enabledRef.current=true;
        setEnabledState(true);
        setState("starting");
        await SecureStore.setItemAsync(VOICE_PREF_KEY,"1");
        scheduleRestart(50);
        return true;
      }catch(e){
        enabledRef.current=false;
        setEnabledState(false);
        setState("error");
        setVoiceError(e?.message||"Could not enable Always Ready.");
        return false;
      }
    }

    enabledRef.current=false;
    conversationRef.current=false;
    busyRef.current=false;
    clearRestart();
    clearConversationTimer();
    try{Speech.stop()}catch{}
    await stopRecognition();
    await SecureStore.deleteItemAsync(VOICE_PREF_KEY);
    setEnabledState(false);
    setState("off");
    setHeard("");
    return true;
  }

  useEffect(()=>{
    let cancelled=false;
    (async()=>{
      const saved=await SecureStore.getItemAsync(VOICE_PREF_KEY);
      if(cancelled||saved!=="1")return;
      const permission=await ExpoSpeechRecognitionModule.getPermissionsAsync().catch(()=>null);
      if(cancelled)return;
      if(permission?.granted){
        enabledRef.current=true;
        setEnabledState(true);
        setState("starting");
        scheduleRestart(300);
      }else{
        await SecureStore.deleteItemAsync(VOICE_PREF_KEY);
      }
    })();
    return ()=>{
      cancelled=true;
      enabledRef.current=false;
      clearRestart();
      clearConversationTimer();
      try{Speech.stop()}catch{}
      try{ExpoSpeechRecognitionModule.abort()}catch{}
    };
  },[]);

  const label={
    off:"Off",
    starting:"Starting…",
    listening:'Listening for “RONN”',
    awake:"Listening",
    thinking:"Thinking…",
    speaking:"Speaking…",
    permission:"Permission needed",
    error:"Needs attention",
  }[state]||state;

  return {
    enabled,
    setEnabled,
    state,
    label,
    heard,
    error:voiceError,
    conversationActive:conversationRef.current,
  };
}
