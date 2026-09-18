import React, {useEffect, useMemo, useRef, useState} from "react";
import {
  ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, SafeAreaView,
  StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View
} from "react-native";
import * as SecureStore from "expo-secure-store";
import * as LocalAuthentication from "expo-local-authentication";

const API="https://ronn-core.onrender.com/api/v1";
const ACCOUNT="ronn_primary";
const SESSION_KEY="ronn_op_session";
const DEVICE_KEY="ronn_device_id";

async function deviceId(){
  let id=await SecureStore.getItemAsync(DEVICE_KEY);
  if(!id){id="ios_"+Date.now().toString(36)+Math.random().toString(36).slice(2,10);await SecureStore.setItemAsync(DEVICE_KEY,id)}
  return id;
}
async function headers(session,extra={}){
  const did=await deviceId();
  return {"Content-Type":"application/json","X-RONN-Account":ACCOUNT,"X-RONN-Client":did,"X-RONN-Device":did,...(session?{"X-RONN-OP-Session":session}:{}),...extra};
}

export default function App(){
  const [session,setSession]=useState("");
  const [unlock,setUnlock]=useState("");
  const [messages,setMessages]=useState([]);
  const [text,setText]=useState("");
  const [busy,setBusy]=useState(false);
  const [conversationId,setConversationId]=useState(null);
  const [error,setError]=useState("");
  const listRef=useRef(null);

  useEffect(()=>{(async()=>{
    const saved=await SecureStore.getItemAsync(SESSION_KEY);
    if(saved){
      try{
        const auth=await LocalAuthentication.hasHardwareAsync();
        if(auth){
          const r=await LocalAuthentication.authenticateAsync({promptMessage:"Unlock RONN",fallbackLabel:"Use device passcode"});
          if(!r.success)return;
        }
        setSession(saved);
      }catch{setSession(saved)}
    }
  })()},[]);

  useEffect(()=>{if(messages.length)setTimeout(()=>listRef.current?.scrollToEnd({animated:true}),40)},[messages,busy]);

  async function unlockOwner(){
    setError("");
    if(!unlock.trim())return;
    try{
      const did=await deviceId();
      const r=await fetch(API+"/owner/unlock",{method:"POST",headers:await headers(""),body:JSON.stringify({
        secret:unlock.trim(),device_id:did,device_name:"RONN iPhone",platform:"ios",app_version:"R21",return_token:true
      })});
      const d=await r.json();
      if(!r.ok)throw new Error(d.detail||"Unlock failed.");
      const token=d.session_token||"";
      if(!token)throw new Error("RONN did not return a mobile session.");
      await SecureStore.setItemAsync(SESSION_KEY,token);
      setSession(token);setUnlock("");
    }catch(e){setError(e.message||"Could not unlock RONN.")}
  }

  async function send(){
    const q=text.trim(); if(!q||busy||!session)return;
    setText("");setError("");setBusy(true);
    setMessages(m=>[...m,{id:"u"+Date.now(),role:"user",content:q}]);
    try{
      const history=messages.slice(-24).map(m=>({role:m.role,content:m.content}));
      const r=await fetch(API+"/chat/complete",{method:"POST",headers:await headers(session),body:JSON.stringify({
        message:q,conversation_id:conversationId,project_id:"default",history,images:[],files:[],
        mode:"auto",style:"auto",project_context:"",review:false,agent_mode:true,skill_profile:"auto"
      })});
      const d=await r.json();
      if(r.status===401||r.status===403){
        await SecureStore.deleteItemAsync(SESSION_KEY);setSession("");
        throw new Error("RONN session expired. Unlock again.");
      }
      if(!r.ok)throw new Error(d.detail||"RONN request failed.");
      if(d.conversation_id)setConversationId(d.conversation_id);
      setMessages(m=>[...m,{id:"a"+Date.now(),role:"assistant",content:d.answer||"No answer returned."}]);
    }catch(e){setError(e.message||"RONN could not answer.")}
    finally{setBusy(false)}
  }

  const renderItem=({item})=>(
    <View style={[styles.msg,item.role==="user"?styles.userRow:styles.aiRow]}>
      <View style={item.role==="user"?styles.userBubble:styles.aiBubble}>
        <Text style={styles.msgText}>{item.content}</Text>
      </View>
    </View>
  );

  if(!session){
    return <SafeAreaView style={styles.root}>
      <StatusBar barStyle="light-content"/>
      <View style={styles.unlockWrap}>
        <Text style={styles.logo}>RONN</Text>
        <Text style={styles.unlockTitle}>Unlock RONN</Text>
        <TextInput value={unlock} onChangeText={setUnlock} secureTextEntry placeholder="Owner access code"
          placeholderTextColor="#777" style={styles.unlockInput} returnKeyType="done" onSubmitEditing={unlockOwner}/>
        {!!error&&<Text style={styles.error}>{error}</Text>}
        <TouchableOpacity style={styles.unlockBtn} onPress={unlockOwner}><Text style={styles.unlockBtnText}>Continue</Text></TouchableOpacity>
      </View>
    </SafeAreaView>
  }

  return <SafeAreaView style={styles.root}>
    <StatusBar barStyle="light-content"/>
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS==="ios"?"padding":undefined} keyboardVerticalOffset={0}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.headerBtn}><Text style={styles.headerGlyph}>☰</Text></TouchableOpacity>
        <Text style={styles.headerTitle}>RONN</Text>
        <TouchableOpacity style={styles.headerBtn} onPress={()=>{setMessages([]);setConversationId(null)}}><Text style={styles.headerGlyph}>＋</Text></TouchableOpacity>
      </View>

      <FlatList ref={listRef} data={messages} keyExtractor={x=>x.id} renderItem={renderItem}
        contentContainerStyle={styles.list} keyboardShouldPersistTaps="handled"
        ListEmptyComponent={<View style={styles.empty}><Text style={styles.emptyTitle}>How can I help?</Text></View>}/>

      {!!error&&<Text style={styles.errorBar}>{error}</Text>}
      {busy&&<View style={styles.working}><ActivityIndicator size="small"/><Text style={styles.workingText}>RONN is working…</Text></View>}

      <View style={styles.composer}>
        <TextInput value={text} onChangeText={setText} placeholder="Message RONN…" placeholderTextColor="#aaa"
          style={styles.input} multiline maxLength={12000} onFocus={()=>setTimeout(()=>listRef.current?.scrollToEnd({animated:true}),80)}/>
        <View style={styles.composerBottom}>
          <TouchableOpacity style={styles.circleGhost}><Text style={styles.plus}>＋</Text></TouchableOpacity>
          <View style={styles.spacer}/>
          <TouchableOpacity style={[styles.send,!text.trim()&&styles.sendDisabled]} onPress={send} disabled={!text.trim()||busy}>
            <Text style={styles.sendText}>{busy?"■":"↑"}</Text>
          </TouchableOpacity>
        </View>
      </View>
    </KeyboardAvoidingView>
  </SafeAreaView>
}

const styles=StyleSheet.create({
  root:{flex:1,backgroundColor:"#212121"},flex:{flex:1},
  header:{height:50,flexDirection:"row",alignItems:"center",justifyContent:"space-between",paddingHorizontal:10,borderBottomWidth:StyleSheet.hairlineWidth,borderBottomColor:"#303030"},
  headerBtn:{width:40,height:40,alignItems:"center",justifyContent:"center"},headerGlyph:{color:"#eee",fontSize:23},headerTitle:{color:"#f4f4f4",fontSize:15,fontWeight:"600"},
  list:{paddingHorizontal:14,paddingTop:18,paddingBottom:18,flexGrow:1},empty:{flex:1,alignItems:"center",justifyContent:"center",minHeight:460},emptyTitle:{color:"#f2f2f2",fontSize:28,fontWeight:"600"},
  msg:{marginBottom:18},userRow:{alignItems:"flex-end"},aiRow:{alignItems:"stretch"},userBubble:{maxWidth:"84%",backgroundColor:"#303030",borderRadius:21,paddingVertical:10,paddingHorizontal:14},
  aiBubble:{paddingHorizontal:2},msgText:{color:"#f2f2f2",fontSize:16,lineHeight:24},
  composer:{marginHorizontal:8,marginBottom:8,backgroundColor:"#303030",borderWidth:1,borderColor:"#444",borderRadius:29,paddingTop:8,paddingHorizontal:10,paddingBottom:8,minHeight:108},
  input:{color:"#f5f5f5",fontSize:17,lineHeight:24,minHeight:48,maxHeight:144,paddingHorizontal:8,paddingTop:5,textAlignVertical:"top"},
  composerBottom:{height:44,flexDirection:"row",alignItems:"center"},circleGhost:{width:40,height:40,borderRadius:20,alignItems:"center",justifyContent:"center"},plus:{color:"#f4f4f4",fontSize:30,fontWeight:"300"},spacer:{flex:1},
  send:{width:40,height:40,borderRadius:20,backgroundColor:"#f4f4f4",alignItems:"center",justifyContent:"center"},sendDisabled:{opacity:.35},sendText:{color:"#171717",fontSize:22,fontWeight:"700"},
  working:{flexDirection:"row",gap:8,alignItems:"center",paddingHorizontal:18,paddingBottom:6},workingText:{color:"#aaa",fontSize:12},
  errorBar:{color:"#ff9b9b",fontSize:12,paddingHorizontal:16,paddingBottom:5},
  unlockWrap:{flex:1,justifyContent:"center",padding:28},logo:{color:"#fff",fontSize:18,fontWeight:"700",letterSpacing:1,marginBottom:40},unlockTitle:{color:"#fff",fontSize:28,fontWeight:"600",marginBottom:18},
  unlockInput:{height:52,borderRadius:16,borderWidth:1,borderColor:"#444",backgroundColor:"#2b2b2b",color:"#fff",paddingHorizontal:15,fontSize:16},
  unlockBtn:{height:50,borderRadius:16,backgroundColor:"#f2f2f2",alignItems:"center",justifyContent:"center",marginTop:12},unlockBtnText:{color:"#171717",fontSize:15,fontWeight:"700"},
  error:{color:"#ff9b9b",fontSize:12,marginTop:10}
});
