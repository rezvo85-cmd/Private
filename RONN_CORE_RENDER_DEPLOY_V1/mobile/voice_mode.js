import {useEffect, useRef, useState} from "react";
import {AppState} from "react-native";
import * as SecureStore from "expo-secure-store";
import * as Speech from "expo-speech";
import {setAudioModeAsync} from "expo-audio";
import {isWakeWordAvailable,startWakeWord,stopWakeWord} from "./modules/ronn-wake-word";
import {
  ExpoSpeechRecognitionModule,
  useSpeechRecognitionEvent,
} from "expo-speech-recognition";

const VOICE_PREF_KEY="ronn_voice_always_ready";
const CONVERSATION_TIMEOUT_MS=18000;
const END_OF_TURN_MS=480;
const WARM_INTERVAL_MS=8*60*1000;
const FIRST_STREAM_FLUSH_CHARS=190;
const WAKE_WORD_RE=/\b(?:ronn|ron)\b/i;
const SLEEP_RE=/^\s*(?:go to sleep|sleep|stop listening|that's all|that is all|never ?mind)\s*[.!?]*\s*$/i;

function normalize(text=""){
  return String(text).trim().replace(/\s+/g," ").toLowerCase();
}

function looksSemanticallyComplete(text=""){
  const raw=String(text||"").trim();
  if(!raw)return false;
  const words=raw.toLowerCase().replace(/[.!?,;:]+$/,"").split(/\s+/).filter(Boolean);
  if(words.length<2)return false;
  const last=words[words.length-1];
  const continuation=new Set(["and","or","but","because","so","if","when","while","with","to","of","for","then","like","about","that","which"]);
  if(continuation.has(last))return false;
  if(/[.!?]\s*$/.test(raw))return true;
  if(/^(who|what|when|where|why|how|can|could|would|should|is|are|do|does|did|tell|give|show|find|make|open|start|stop)\b/i.test(raw))return true;
  return words.length>=5;
}

function semanticCommitDelay(text=""){
  const raw=String(text||"").trim();
  const words=raw.split(/\s+/).filter(Boolean);
  if(/[.!?]\s*$/.test(raw))return 220;
  if(/^(who|what|when|where|why|how|can|could|would|should|is|are|do|does|did)\b/i.test(raw)&&words.length>=3)return 320;
  if(words.length>=8)return 380;
  return END_OF_TURN_MS;
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

export function useRonnVoice({askRonn,cancelRonn,warmRonn}){
  const [enabled,setEnabledState]=useState(false);
  const [state,setState]=useState("off");
  const [heard,setHeard]=useState("");
  const [voiceError,setVoiceError]=useState("");
  const [latency,setLatency]=useState(null);

  const enabledRef=useRef(false);
  const listeningRef=useRef(false);
  const busyRef=useRef(false);
  const conversationRef=useRef(false);
  const restartTimerRef=useRef(null);
  const conversationTimerRef=useRef(null);
  const lastFinalRef=useRef("");
  const lastFinalAtRef=useRef(0);
  const askRonnRef=useRef(askRonn);
  const cancelRonnRef=useRef(cancelRonn);
  const warmRonnRef=useRef(warmRonn);
  const voiceIdRef=useRef(null);
  const onDeviceRef=useRef(null);
  const speakingRef=useRef(false);
  const interruptingRef=useRef(false);
  const bargePendingRef=useRef(false);
  const turnSerialRef=useRef(0);
  const currentSpeechRef=useRef("");
  const recentSpeechRef=useRef("");
  const nativeWakeRef=useRef(false);
  const nativeWakeSubRef=useRef(null);
  const wakeTransitionRef=useRef(false);
  const interimTimerRef=useRef(null);
  const keepWarmTimerRef=useRef(null);
  const lastInterimRef=useRef("");
  const lastInterimAtRef=useRef(0);
  const latencyRef=useRef({wakeAt:0,finalAt:0,queryAt:0,firstTokenAt:0,firstSpeechAt:0});

  useEffect(()=>{askRonnRef.current=askRonn},[askRonn]);
  useEffect(()=>{cancelRonnRef.current=cancelRonn},[cancelRonn]);
  useEffect(()=>{warmRonnRef.current=warmRonn},[warmRonn]);

  function clearRestart(){
    if(restartTimerRef.current){
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current=null;
    }
  }

  function clearInterimTimer(){
    if(interimTimerRef.current){
      clearTimeout(interimTimerRef.current);
      interimTimerRef.current=null;
    }
  }

  function clearKeepWarm(){
    if(keepWarmTimerRef.current){
      clearInterval(keepWarmTimerRef.current);
      keepWarmTimerRef.current=null;
    }
  }

  function startKeepWarm(){
    clearKeepWarm();
    if(!enabledRef.current)return;
    try{warmRonnRef.current?.()}catch{}
    keepWarmTimerRef.current=setInterval(()=>{
      if(!enabledRef.current)return;
      try{warmRonnRef.current?.()}catch{}
    },WARM_INTERVAL_MS);
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

  async function bestVoiceId(){
    if(voiceIdRef.current!==null)return voiceIdRef.current;
    try{
      const voices=await Speech.getAvailableVoicesAsync();
      const english=(voices||[]).filter(v=>String(v?.language||"").toLowerCase().startsWith("en-us"));
      const enhanced=english.filter(v=>String(v?.quality||"").toLowerCase()==="enhanced");
      const chosen=enhanced[0]||english[0]||null;
      voiceIdRef.current=chosen?.identifier||"";
    }catch{
      voiceIdRef.current="";
    }
    return voiceIdRef.current;
  }

  function speechReadyText(text=""){
    return String(text||"")
      .replace(/```[\s\S]*?```/g," ")
      .replace(/`([^`]+)`/g,"$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g,"$1")
      .replace(/https?:\/\/\S+/gi," ")
      .replace(/[*_#>|~]+/g," ")
      .replace(/\s+/g," ")
      .trim();
  }

  function speechChunks(text,maxChars=320){
    const clean=speechReadyText(text);
    if(!clean)return [];
    const sentences=clean.match(/[^.!?]+[.!?]+|[^.!?]+$/g)||[clean];
    const chunks=[];
    let current="";
    for(const sentence of sentences){
      const next=(current+" "+sentence.trim()).trim();
      if(current&&next.length>maxChars){
        chunks.push(current);
        current=sentence.trim();
      }else{
        current=next;
      }
    }
    if(current)chunks.push(current);
    return chunks;
  }

  function splitStreamSentences(text=""){
    let rest=String(text||"");
    const sentences=[];
    while(rest){
      const match=rest.match(/^([\s\S]*?[.!?])(?=\s|$)/);
      if(!match)break;
      const sentence=match[1].trim();
      if(sentence)sentences.push(sentence);
      rest=rest.slice(match[0].length).replace(/^\s+/,"");
    }
    if(rest.length>FIRST_STREAM_FLUSH_CHARS){
      const window=rest.slice(0,FIRST_STREAM_FLUSH_CHARS);
      const cut=Math.max(window.lastIndexOf(";"),window.lastIndexOf(","),window.lastIndexOf(" "));
      if(cut>90){
        const sentence=rest.slice(0,cut+1).trim();
        if(sentence)sentences.push(sentence);
        rest=rest.slice(cut+1).replace(/^\s+/,"");
      }
    }
    return {sentences,rest};
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

  async function stopNativeWake(){
    try{nativeWakeSubRef.current?.remove?.()}catch{}
    nativeWakeSubRef.current=null;
    if(nativeWakeRef.current){
      try{await stopWakeWord()}catch{}
    }
    nativeWakeRef.current=false;
  }

  async function handleNativeWake(){
    if(!enabledRef.current||busyRef.current||conversationRef.current)return;
    latencyRef.current={wakeAt:Date.now(),finalAt:0,queryAt:0,firstTokenAt:0,firstSpeechAt:0};
    try{warmRonnRef.current?.()}catch{}
    await stopNativeWake();
    conversationRef.current=true;
    armConversationTimeout();
    setHeard("RONN");
    setVoiceError("");
    setState("awake");
    scheduleRestart(40);
  }

  async function startNativeWake(){
    if(!enabledRef.current||busyRef.current||conversationRef.current||nativeWakeRef.current)return false;
    if(!isWakeWordAvailable())return false;
    wakeTransitionRef.current=true;
    try{
      await stopRecognition();
      await configureAudio();
      const subscription=await startWakeWord("RONN",()=>{handleNativeWake()});
      if(!subscription)return false;
      nativeWakeSubRef.current=subscription;
      nativeWakeRef.current=true;
      setVoiceError("");
      setState("listening");
      return true;
    }catch(e){
      nativeWakeRef.current=false;
      setVoiceError(e?.message||"RONN wake-word listener could not start.");
      return false;
    }finally{
      wakeTransitionRef.current=false;
    }
  }

  function canUseOnDeviceRecognition(){
    if(onDeviceRef.current!==null)return onDeviceRef.current;
    try{
      onDeviceRef.current=ExpoSpeechRecognitionModule.supportsOnDeviceRecognition?.()===true;
    }catch{
      onDeviceRef.current=false;
    }
    return onDeviceRef.current;
  }

  async function startRecognition({allowWhileBusy=false}={}){
    if(!enabledRef.current||(!allowWhileBusy&&busyRef.current)||listeningRef.current)return;
    clearRestart();
    try{
      const permission=await ExpoSpeechRecognitionModule.getPermissionsAsync();
      if(!permission?.granted){
        setState("permission");
        setVoiceError("Microphone and speech recognition permission are required.");
        return;
      }
      await stopNativeWake();
      await configureAudio();
      setVoiceError("");
      if(!speakingRef.current)setState(conversationRef.current?"awake":"starting");
      ExpoSpeechRecognitionModule.start({
        lang:"en-US",
        interimResults:true,
        continuous:true,
        maxAlternatives:1,
        contextualStrings:["RONN","Ronn","Ron"],
        requiresOnDeviceRecognition:canUseOnDeviceRecognition(),
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
      scheduleRestart(1200,allowWhileBusy);
    }
  }

  function scheduleRestart(delay=140,allowWhileBusy=false){
    if(!enabledRef.current||(!allowWhileBusy&&busyRef.current))return;
    clearRestart();
    restartTimerRef.current=setTimeout(async()=>{
      if(!enabledRef.current||(!allowWhileBusy&&busyRef.current))return;
      if(!conversationRef.current&&!allowWhileBusy){
        const started=await startNativeWake();
        if(started)return;
      }
      startRecognition({allowWhileBusy});
    },delay);
  }

  async function stopRecognition(){
    clearRestart();
    if(listeningRef.current){
      try{ExpoSpeechRecognitionModule.abort()}catch{}
    }
    listeningRef.current=false;
  }

  function finishSpeaking(){
    busyRef.current=false;
    if(!enabledRef.current){
      setState("off");
      return;
    }
    setState(conversationRef.current?"awake":"starting");
    scheduleRestart(90);
  }

  async function speak(text,turnId=turnSerialRef.current){
    const chunks=speechChunks(text);
    if(!chunks.length)return;
    await configureAudio();
    if(turnId!==turnSerialRef.current)return;
    speakingRef.current=true;
    setState("speaking");
    if(latencyRef.current.queryAt&&!latencyRef.current.firstSpeechAt){
      latencyRef.current.firstSpeechAt=Date.now();
      const m={
        wakeToFinalMs:latencyRef.current.wakeAt&&latencyRef.current.finalAt?latencyRef.current.finalAt-latencyRef.current.wakeAt:null,
        finalToQueryMs:latencyRef.current.finalAt?latencyRef.current.queryAt-latencyRef.current.finalAt:null,
        queryToFirstTokenMs:latencyRef.current.firstTokenAt?latencyRef.current.firstTokenAt-latencyRef.current.queryAt:null,
        queryToFirstSpeechMs:latencyRef.current.firstSpeechAt-latencyRef.current.queryAt,
      };
      setLatency(m);
      try{console.log("[RONN_VOICE_LATENCY]",JSON.stringify(m))}catch{}
    }
    const voice=await bestVoiceId();
    for(const words of chunks){
      if(turnId!==turnSerialRef.current||interruptingRef.current||bargePendingRef.current||!enabledRef.current)break;
      currentSpeechRef.current=words;
      recentSpeechRef.current=(recentSpeechRef.current+" "+words).slice(-900);
      scheduleRestart(40,true);
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
            rate:0.95,
            pitch:0.96,
            useApplicationAudioSession:true,
            ...(voice?{voice}:{}),
            onDone:done,
            onStopped:done,
            onError:done,
          });
        }catch{
          done();
        }
        setTimeout(done,Math.min(90000,Math.max(7000,words.length*90)));
      });
      if(!enabledRef.current||turnId!==turnSerialRef.current||interruptingRef.current||bargePendingRef.current)break;
    }
    currentSpeechRef.current="";
    if(turnId===turnSerialRef.current) {
      speakingRef.current=false;
    }
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
    const turnId=++turnSerialRef.current;
    clearInterimTimer();
    latencyRef.current={...latencyRef.current,queryAt:Date.now(),firstTokenAt:0,firstSpeechAt:0};
    setLatency(null);
    busyRef.current=true;
    speakingRef.current=false;
    interruptingRef.current=false;
    bargePendingRef.current=false;
    recentSpeechRef.current="";
    await stopRecognition();
    conversationRef.current=true;
    armConversationTimeout();
    setState("thinking");
    setVoiceError("");

    let pendingSpeech="";
    let spokeAny=false;
    let speechChain=Promise.resolve();

    const queueSpeech=(text)=>{
      const words=String(text||"").trim();
      if(!words||turnId!==turnSerialRef.current)return;
      spokeAny=true;
      speechChain=speechChain.then(()=>{
        if(turnId!==turnSerialRef.current)return;
        return speak(words,turnId);
      });
    };

    const handleToken=(token)=>{
      if(turnId!==turnSerialRef.current)return;
      if(!latencyRef.current.firstTokenAt)latencyRef.current.firstTokenAt=Date.now();
      pendingSpeech+=String(token||"");
      const split=splitStreamSentences(pendingSpeech);
      pendingSpeech=split.rest;
      for(const sentence of split.sentences)queueSpeech(sentence);
    };

    try{
      const answer=await askRonnRef.current?.(q,handleToken);
      if(turnId!==turnSerialRef.current)return;
      const tail=speechReadyText(pendingSpeech);
      if(tail)queueSpeech(tail);
      await speechChain;
      if(turnId!==turnSerialRef.current)return;

      if(!spokeAny){
        if(answer){
          await speak(answer,turnId);
        }else{
          await speak("I couldn't get an answer right now.",turnId);
        }
      }
    }catch(e){
      if(turnId!==turnSerialRef.current)return;
      setVoiceError(e?.message||"RONN could not answer.");
      try{await speechChain}catch{}
      if(!spokeAny)await speak("I couldn't reach RONN right now.",turnId);
    }finally{
      if(turnId===turnSerialRef.current){
        speakingRef.current=false;
        finishSpeaking();
      }
    }
  }

  function looksLikeSpeechEcho(transcript){
    const heardWords=normalize(transcript).split(" ").filter(Boolean);
    if(!heardWords.length)return true;
    const speech=normalize(currentSpeechRef.current+" "+recentSpeechRef.current.slice(-260));
    const heard=heardWords.join(" ");
    if(!speech)return false;
    if(speech.includes(heard))return true;
    const unique=[...new Set(heardWords.filter(w=>w.length>2))];
    if(unique.length<2)return false;
    const overlap=unique.filter(w=>speech.includes(w)).length/unique.length;
    return overlap>=0.8;
  }

  async function interruptWithTranscript(transcript){
    const raw=String(transcript||"").trim();
    if(!raw||interruptingRef.current)return;
    if(looksLikeSpeechEcho(raw)){
      bargePendingRef.current=false;
      return;
    }
    interruptingRef.current=true;
    bargePendingRef.current=false;
    turnSerialRef.current+=1;
    try{Speech.stop()}catch{}
    try{cancelRonnRef.current?.()}catch{}
    busyRef.current=false;
    speakingRef.current=false;
    currentSpeechRef.current="";
    await stopRecognition();
    setHeard(raw);

    if(SLEEP_RE.test(raw)){
      interruptingRef.current=false;
      await goToSleep();
      return;
    }

    interruptingRef.current=false;
    await runQuery(raw);
  }

  async function handleFinalTranscript(transcript){
    clearInterimTimer();
    const raw=String(transcript||"").trim();
    if(!raw)return;
    if(speakingRef.current||interruptingRef.current){
      await interruptWithTranscript(raw);
      return;
    }
    if(busyRef.current)return;
    const normalized=normalize(raw);
    const now=Date.now();
    if(normalized===lastFinalRef.current&&now-lastFinalAtRef.current<2200)return;
    lastFinalRef.current=normalized;
    lastFinalAtRef.current=now;
    latencyRef.current.finalAt=now;

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
    try{warmRonnRef.current?.()}catch{}
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
    if(!speakingRef.current)setState(conversationRef.current?"awake":"listening");
    setVoiceError("");
  });

  useSpeechRecognitionEvent("end",()=>{
    listeningRef.current=false;
    if(wakeTransitionRef.current)return;
    if(!enabledRef.current)return;
    if(speakingRef.current&&busyRef.current){
      scheduleRestart(180,true);
      return;
    }
    if(!busyRef.current){
      setState(conversationRef.current?"awake":"starting");
      scheduleRestart(250);
    }
  });

  function scheduleSemanticCommit(transcript){
    const clean=String(transcript||"").trim();
    if(!conversationRef.current||busyRef.current||speakingRef.current||!looksSemanticallyComplete(clean)){
      clearInterimTimer();
      return;
    }
    const delay=semanticCommitDelay(clean);
    lastInterimRef.current=clean;
    lastInterimAtRef.current=Date.now();
    clearInterimTimer();
    interimTimerRef.current=setTimeout(()=>{
      if(!enabledRef.current||busyRef.current||speakingRef.current)return;
      if(Date.now()-lastInterimAtRef.current<delay-20)return;
      handleFinalTranscript(lastInterimRef.current);
    },delay);
  }

  useSpeechRecognitionEvent("result",(event)=>{
    const transcript=event?.results?.[0]?.transcript||"";
    if(transcript)setHeard(transcript);

    if(speakingRef.current&&transcript&&!event?.isFinal){
      const clean=String(transcript).trim();
      const enoughSpeech=clean.length>=6&&clean.split(/\s+/).length>=2;
      if(enoughSpeech&&!looksLikeSpeechEcho(clean)){
        bargePendingRef.current=true;
        try{Speech.stop()}catch{}
        currentSpeechRef.current="";
      }
    }

    if(!event?.isFinal&&transcript&&!speakingRef.current){
      scheduleSemanticCommit(transcript);
    }

    if(event?.isFinal&&transcript){
      handleFinalTranscript(transcript);
    }
  });

  useSpeechRecognitionEvent("error",(event)=>{
    listeningRef.current=false;
    const code=String(event?.error||"");
    if(wakeTransitionRef.current&&["aborted","interrupted","no-speech"].includes(code))return;
    if(!["aborted","no-speech","interrupted"].includes(code)){
      setVoiceError(event?.message||code||"Speech recognition stopped.");
    }
    if(onDeviceRef.current===true&&["language-not-supported","service-not-allowed"].includes(code)){
      onDeviceRef.current=false;
      setVoiceError("");
      scheduleRestart(250,speakingRef.current&&busyRef.current);
      return;
    }
    if(code==="audio-capture"){
      setVoiceError("");
      scheduleRestart(180,speakingRef.current&&busyRef.current);
      return;
    }
    if(!enabledRef.current)return;
    if(speakingRef.current&&busyRef.current){
      if(!["aborted","no-speech"].includes(code))scheduleRestart(350,true);
      return;
    }
    if(busyRef.current)return;
    if(code==="not-allowed"){
      scheduleRestart(1800);
      return;
    }
    if(code==="interrupted"){
      setState("starting");
      scheduleRestart(1500);
      return;
    }
    scheduleRestart(500);
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
        startKeepWarm();
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
    speakingRef.current=false;
    interruptingRef.current=false;
    bargePendingRef.current=false;
    turnSerialRef.current+=1;
    try{cancelRonnRef.current?.()}catch{}
    clearRestart();
    clearConversationTimer();
    clearInterimTimer();
    clearKeepWarm();
    try{Speech.stop()}catch{}
    await stopRecognition();
    await stopNativeWake();
    await SecureStore.deleteItemAsync(VOICE_PREF_KEY);
    setEnabledState(false);
    setState("off");
    setHeard("");
    return true;
  }

  useEffect(()=>{
    const sub=AppState.addEventListener("change",(nextState)=>{
      if(!enabledRef.current||busyRef.current)return;
      setVoiceError("");
      if(conversationRef.current){
        if(nextState==="active"&&!listeningRef.current){
          setState("awake");
          scheduleRestart(150);
        }
        return;
      }
      if(!nativeWakeRef.current){
        setState("starting");
        scheduleRestart(80);
      }
    });
    return ()=>sub.remove();
  },[]);

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
        startKeepWarm();
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
      clearInterimTimer();
      clearKeepWarm();
      try{Speech.stop()}catch{}
      try{ExpoSpeechRecognitionModule.abort()}catch{}
      try{nativeWakeSubRef.current?.remove?.()}catch{}
      nativeWakeSubRef.current=null;
      nativeWakeRef.current=false;
      try{stopWakeWord()}catch{}
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
    latency,
  };
}
