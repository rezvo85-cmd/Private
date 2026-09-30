import {requireNativeModule} from "expo-modules-core";

let nativeModule=null;
try{
  nativeModule=requireNativeModule("RonnWakeWord");
}catch{}

export const isWakeWordAvailable=()=>!!nativeModule;

export async function startWakeWord(keyword="RONN",onWake){
  if(!nativeModule)return false;
  const subscription=typeof nativeModule.addListener==="function"
    ?nativeModule.addListener("onWakeWord",event=>onWake?.(event?.keyword||keyword))
    :null;
  try{
    const started=await nativeModule.start(keyword);
    if(!started){
      subscription?.remove?.();
      return false;
    }
    return {remove:()=>subscription?.remove?.()};
  }catch{
    subscription?.remove?.();
    return false;
  }
}

export async function stopWakeWord(){
  if(!nativeModule)return false;
  try{return await nativeModule.stop()}catch{return false}
}

export async function wakeWordStatus(){
  if(!nativeModule)return {available:false,running:false};
  try{
    return {
      available:!!(await nativeModule.isSupported()),
      running:!!(await nativeModule.isRunning())
    };
  }catch{
    return {available:false,running:false};
  }
}
