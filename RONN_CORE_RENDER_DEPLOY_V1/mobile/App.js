import React, {useEffect, useRef, useState} from "react";
import {
  ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, SafeAreaView,
  StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View
} from "react-native";
import * as SecureStore from "expo-secure-store";

const API="https://ronn-core.onrender.com/api/v1";
const OWNER_ACCOUNT="ronn_primary";
const SESSION_KEY="ronn_op_session";
const DEVICE_KEY="ronn_device_id";

async function deviceId(){
  let id=await SecureStore.getItemAsync(DEVICE_KEY);
  if(!id){
    id="ios_"+Date.now().toString(36)+Math.random().toString(36).slice(2,10);
    await SecureStore.setItemAsync(DEVICE_KEY,id);
  }
  return id;
}

async function headers(session="",extra={},ownerMode=false){
  const did=await deviceId();
  const h={
    "Content-Type":"application/json",
    "X-RONN-Client":did,
    "X-RONN-Device":did,
    ...extra,
  };
  if(ownerMode||session)h["X-RONN-Account"]=OWNER_ACCOUNT;
  if(session)h["X-RONN-OP-Session"]=session;
  return h;
}

export default function App(){
  const [session,setSession]=useState("");
  const [screen,setScreen]=useState("chat");
  const [unlock,setUnlock]=useState("");
  const [messages,setMessages]=useState([]);
  const [text,setText]=useState("");
  const [busy,setBusy]=useState(false);
  const [conversationId,setConversationId]=useState(null);
  const [error,setError]=useState("");
  const [opBusy,setOpBusy]=useState(false);
  const listRef=useRef(null);

  useEffect(()=>{(async()=>{
    const saved=await SecureStore.getItemAsync(SESSION_KEY);
    if(!saved)return;
    try{
      const r=await fetch(API+"/owner/status",{headers:await headers(saved,{},true)});
      const d=await r.json();
      if(r.ok&&d.op_active)setSession(saved);
      else await SecureStore.deleteItemAsync(SESSION_KEY);
    }catch{}
  })()},[]);

  useEffect(()=>{
    if(messages.length&&screen==="chat"){
      setTimeout(()=>listRef.current?.scrollToEnd({animated:true}),40);
    }
  },[messages,busy,screen]);

  function resetChat(){
    setMessages([]);
    setConversationId(null);
    setError("");
  }

  async function enableOp(){
    const code=unlock.trim();
    if(!code||opBusy)return;
    setError("");setOpBusy(true);
    try{
      const did=await deviceId();
      const r=await fetch(API+"/owner/unlock",{
        method:"POST",
        headers:await headers("",{},true),
        body:JSON.stringify({
          secret:code,
          device_id:did,
          device_name:"RONN iPhone",
          platform:"ios",
          app_version:"R21",
          return_token:true
        })
      });
      const d=await r.json();
      if(!r.ok)throw new Error(d.detail||"Could not enable OP Access.");
      const token=d.session_token||"";
      if(!token)throw new Error("RONN did not return an OP session.");
      await SecureStore.setItemAsync(SESSION_KEY,token);
      setSession(token);
      setUnlock("");
      resetChat();
    }catch(e){
      setError(e.message||"Could not enable OP Access.");
    }finally{
      setOpBusy(false);
    }
  }

  async function disableOp(){
    if(opBusy)return;
    setError("");setOpBusy(true);
    try{
      if(session){
        await fetch(API+"/owner/lock",{
          method:"POST",
          headers:await headers(session,{},true),
          body:"{}"
        });
      }
    }catch{}
    await SecureStore.deleteItemAsync(SESSION_KEY);
    setSession("");
    setUnlock("");
    resetChat();
    setOpBusy(false);
  }

  async function performChat(q,activeSession){
    const history=messages.slice(-24).map(m=>({role:m.role,content:m.content}));
    return fetch(API+"/chat/complete",{
      method:"POST",
      headers:await headers(activeSession,{},!!activeSession),
      body:JSON.stringify({
        message:q,
        conversation_id:conversationId,
        project_id:"default",
        history,
        images:[],
        files:[],
        mode:"auto",
        style:"auto",
        project_context:"",
        review:false,
        agent_mode:true,
        skill_profile:"auto"
      })
    });
  }

  async function send(){
    const q=text.trim();
    if(!q||busy)return;
    setText("");setError("");setBusy(true);
    setMessages(m=>[...m,{id:"u"+Date.now(),role:"user",content:q}]);

    try{
      let r=await performChat(q,session);
      if((r.status===401||r.status===403)&&session){
        await SecureStore.deleteItemAsync(SESSION_KEY);
        setSession("");
        setConversationId(null);
        r=await performChat(q,"");
      }
      const d=await r.json();
      if(!r.ok)throw new Error(d.detail||"RONN request failed.");
      if(d.conversation_id)setConversationId(d.conversation_id);
      setMessages(m=>[...m,{
        id:"a"+Date.now(),
        role:"assistant",
        content:d.answer||"No answer returned.",
        meta:d.meta||{}
      }]);
    }catch(e){
      setError(e.message||"RONN could not answer.");
    }finally{
      setBusy(false);
    }
  }

  const renderItem=({item})=>{
    const hub=item?.meta?.tool_hub||{};
    const weather=hub?.presentation?.type==="weather"?hub.presentation:null;
    const sources=Array.isArray(hub?.sources)?hub.sources.slice(0,4):[];
    return <View style={[styles.msg,item.role==="user"?styles.userRow:styles.aiRow]}>
      <View style={item.role==="user"?styles.userBubble:styles.aiBubble}>
        <Text style={styles.msgText}>{item.content}</Text>
        {!!weather&&<View style={styles.weatherCard}>
          <View style={styles.weatherTop}>
            <View style={styles.weatherPlaceWrap}>
              <Text style={styles.cardLabel}>WEATHER</Text>
              <Text style={styles.weatherPlace}>{weather.location}</Text>
            </View>
            <Text style={styles.weatherTemp}>{Math.round(Number(weather.temperature_f||0))}°F</Text>
          </View>
          <Text style={styles.weatherDetail}>
            {weather.condition} · Feels like {Math.round(Number(weather.feels_like_f||0))}° · Wind {Math.round(Number(weather.wind_mph||0))} mph
          </Text>
        </View>}
        {!!sources.length&&<View style={styles.sources}>
          <Text style={styles.cardLabel}>SOURCES</Text>
          {sources.map((s,i)=><Text key={String(i)} style={styles.sourceText} numberOfLines={1}>{s.title||s.url}</Text>)}
        </View>}
      </View>
    </View>
  };

  if(screen==="settings"){
    return <SafeAreaView style={styles.root}>
      <StatusBar barStyle="light-content"/>
      <View style={styles.header}>
        <TouchableOpacity style={styles.headerBtn} onPress={()=>{setScreen("chat");setError("")}}>
          <Text style={styles.headerGlyph}>‹</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Settings</Text>
        <View style={styles.headerBtn}/>
      </View>

      <View style={styles.settings}>
        <Text style={styles.settingsSection}>ACCESS</Text>
        <View style={styles.settingsCard}>
          <View style={styles.settingsRow}>
            <View style={styles.settingsTextWrap}>
              <Text style={styles.settingsTitle}>OP Access</Text>
              <Text style={styles.settingsSub}>
                {session?"Enabled on this device":"Optional. Normal RONN chat works without it."}
              </Text>
            </View>
            <View style={[styles.statusPill,session?styles.statusOn:styles.statusOff]}>
              <Text style={styles.statusText}>{session?"ON":"OFF"}</Text>
            </View>
          </View>

          {!session&&<>
            <TextInput
              value={unlock}
              onChangeText={setUnlock}
              secureTextEntry
              placeholder="OP access code"
              placeholderTextColor="#777"
              style={styles.settingsInput}
              returnKeyType="done"
              onSubmitEditing={enableOp}
            />
            <TouchableOpacity style={styles.primaryBtn} onPress={enableOp} disabled={opBusy||!unlock.trim()}>
              {opBusy?<ActivityIndicator color="#171717"/>:<Text style={styles.primaryBtnText}>Enable OP Access</Text>}
            </TouchableOpacity>
          </>}

          {!!session&&<TouchableOpacity style={styles.dangerBtn} onPress={disableOp} disabled={opBusy}>
            {opBusy?<ActivityIndicator color="#fff"/>:<Text style={styles.dangerBtnText}>Disable OP Access</Text>}
          </TouchableOpacity>}

          {!!error&&<Text style={styles.settingsError}>{error}</Text>}
        </View>

        <Text style={styles.settingsNote}>
          OP Access unlocks the private owner account, admin tools, developer controls, and owner-only features. It is not required for normal chat.
        </Text>
      </View>
    </SafeAreaView>
  }

  return <SafeAreaView style={styles.root}>
    <StatusBar barStyle="light-content"/>
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS==="ios"?"padding":undefined} keyboardVerticalOffset={0}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.headerBtn} onPress={()=>{setScreen("settings");setError("")}}>
          <Text style={styles.headerGlyph}>☰</Text>
        </TouchableOpacity>
        <View style={styles.headerCenter}>
          <Text style={styles.headerTitle}>RONN</Text>
          {!!session&&<View style={styles.opDot}/>}
        </View>
        <TouchableOpacity style={styles.headerBtn} onPress={resetChat}>
          <Text style={styles.headerGlyph}>＋</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={x=>x.id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={<View style={styles.empty}>
          <Text style={styles.emptyTitle}>How can I help?</Text>
          <Text style={styles.emptySub}>{session?"OP Access enabled":"RONN is ready"}</Text>
        </View>}
      />

      {!!error&&<Text style={styles.errorBar}>{error}</Text>}
      {busy&&<View style={styles.working}>
        <ActivityIndicator size="small"/>
        <Text style={styles.workingText}>RONN is working…</Text>
      </View>}

      <View style={styles.composer}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="Message RONN…"
          placeholderTextColor="#aaa"
          style={styles.input}
          multiline
          maxLength={12000}
          onFocus={()=>setTimeout(()=>listRef.current?.scrollToEnd({animated:true}),80)}
        />
        <View style={styles.composerBottom}>
          <TouchableOpacity style={styles.circleGhost}>
            <Text style={styles.plus}>＋</Text>
          </TouchableOpacity>
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
  headerBtn:{width:40,height:40,alignItems:"center",justifyContent:"center"},
  headerGlyph:{color:"#eee",fontSize:23},
  headerCenter:{flexDirection:"row",alignItems:"center",gap:6},
  headerTitle:{color:"#f4f4f4",fontSize:15,fontWeight:"600"},
  opDot:{width:6,height:6,borderRadius:3,backgroundColor:"#ff4b4b"},
  list:{paddingHorizontal:14,paddingTop:18,paddingBottom:18,flexGrow:1},
  empty:{flex:1,alignItems:"center",justifyContent:"center",minHeight:460},
  emptyTitle:{color:"#f2f2f2",fontSize:28,fontWeight:"600"},
  emptySub:{color:"#8f8f8f",fontSize:12,marginTop:8},
  msg:{marginBottom:18},userRow:{alignItems:"flex-end"},aiRow:{alignItems:"stretch"},
  userBubble:{maxWidth:"84%",backgroundColor:"#303030",borderRadius:21,paddingVertical:10,paddingHorizontal:14},
  aiBubble:{paddingHorizontal:2},msgText:{color:"#f2f2f2",fontSize:16,lineHeight:24},
  composer:{marginHorizontal:8,marginBottom:8,backgroundColor:"#303030",borderWidth:1,borderColor:"#444",borderRadius:29,paddingTop:8,paddingHorizontal:10,paddingBottom:8,minHeight:108},
  input:{color:"#f5f5f5",fontSize:17,lineHeight:24,minHeight:48,maxHeight:144,paddingHorizontal:8,paddingTop:5,textAlignVertical:"top"},
  composerBottom:{height:44,flexDirection:"row",alignItems:"center"},
  circleGhost:{width:40,height:40,borderRadius:20,alignItems:"center",justifyContent:"center"},
  plus:{color:"#f4f4f4",fontSize:30,fontWeight:"300"},spacer:{flex:1},
  send:{width:40,height:40,borderRadius:20,backgroundColor:"#f4f4f4",alignItems:"center",justifyContent:"center"},
  sendDisabled:{opacity:.35},sendText:{color:"#171717",fontSize:22,fontWeight:"700"},
  working:{flexDirection:"row",gap:8,alignItems:"center",paddingHorizontal:18,paddingBottom:6},
  workingText:{color:"#aaa",fontSize:12},errorBar:{color:"#ff9b9b",fontSize:12,paddingHorizontal:16,paddingBottom:5},
  weatherCard:{marginTop:12,backgroundColor:"#292929",borderWidth:1,borderColor:"#3e3e3e",borderRadius:17,padding:13},
  weatherTop:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},
  weatherPlaceWrap:{flex:1,paddingRight:10},cardLabel:{color:"#999",fontSize:9,fontWeight:"700",letterSpacing:1.1},
  weatherPlace:{color:"#f4f4f4",fontSize:14,fontWeight:"600",marginTop:3},
  weatherTemp:{color:"#fff",fontSize:27,fontWeight:"700"},
  weatherDetail:{color:"#bbb",fontSize:12,lineHeight:18,marginTop:6},
  sources:{marginTop:10,gap:5},
  sourceText:{color:"#cfcfcf",fontSize:11,backgroundColor:"#292929",borderRadius:9,paddingHorizontal:9,paddingVertical:7},

  settings:{padding:16,gap:12},
  settingsSection:{color:"#888",fontSize:11,fontWeight:"700",letterSpacing:1.1,marginTop:8,marginLeft:4},
  settingsCard:{backgroundColor:"#292929",borderRadius:20,borderWidth:1,borderColor:"#393939",padding:15},
  settingsRow:{flexDirection:"row",alignItems:"center",gap:12},
  settingsTextWrap:{flex:1},
  settingsTitle:{color:"#f4f4f4",fontSize:16,fontWeight:"600"},
  settingsSub:{color:"#9f9f9f",fontSize:12,lineHeight:17,marginTop:3},
  statusPill:{minWidth:42,height:24,borderRadius:12,alignItems:"center",justifyContent:"center",paddingHorizontal:9},
  statusOn:{backgroundColor:"#5b1e1e"},statusOff:{backgroundColor:"#383838"},
  statusText:{color:"#fff",fontSize:10,fontWeight:"800"},
  settingsInput:{height:50,borderRadius:15,borderWidth:1,borderColor:"#444",backgroundColor:"#242424",color:"#fff",paddingHorizontal:14,fontSize:15,marginTop:16},
  primaryBtn:{height:48,borderRadius:15,backgroundColor:"#f2f2f2",alignItems:"center",justifyContent:"center",marginTop:10},
  primaryBtnText:{color:"#171717",fontSize:14,fontWeight:"700"},
  dangerBtn:{height:48,borderRadius:15,backgroundColor:"#7a2727",alignItems:"center",justifyContent:"center",marginTop:16},
  dangerBtnText:{color:"#fff",fontSize:14,fontWeight:"700"},
  settingsError:{color:"#ff9b9b",fontSize:12,marginTop:10},
  settingsNote:{color:"#777",fontSize:11,lineHeight:17,paddingHorizontal:4}
});
