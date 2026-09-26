const $ = id => document.getElementById(id);
const qsa = s => [...document.querySelectorAll(s)];
function safeGet(k){try{return window.localStorage.getItem(k)}catch{return null}}
function safeSet(k,v){try{window.localStorage.setItem(k,v);return true}catch{return false}}
function safeRemove(k){try{window.localStorage.removeItem(k);return true}catch{return false}}
const messages = $("messages"), input = $("input"), sendBtn = $("sendBtn"), stopBtn = $("stopBtn");
const attachmentsEl = $("attachments"), fileInput = $("fileInput"), jumpLatest = $("jumpLatest");
const routeBadge = $("routeBadge"), stageBadge = $("stageBadge"), profileBadge = $("profileBadge");

const BUILD_EXPECTED = "RONN-COGNITIVE-OS-2026-R23-ALL-11";
const CORE_API = "/api/v1";
const CLIENT_KEY = "ronnClient";
const LEGACY_CLIENT_KEY = "novaUltraClient";
let clientId = safeGet(CLIENT_KEY) || safeGet(LEGACY_CLIENT_KEY);
if(!clientId){
  clientId=(crypto.randomUUID?crypto.randomUUID():"ronn-"+Date.now()+"-"+Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g,"");
}
safeSet(CLIENT_KEY,clientId);
const DEVICE_KEY="ronnDevice";
let deviceId=safeGet(DEVICE_KEY);
if(!deviceId){deviceId=(crypto.randomUUID?crypto.randomUUID():"dev-"+Date.now()+"-"+Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g,"");safeSet(DEVICE_KEY,deviceId);}
const apiHeaders = extra => Object.assign({"X-RONN-Client":clientId,"X-RONN-Device":deviceId,"X-RONN-Account":"ronn_primary"},extra||{});

function setWebAuthGate(show,message="") {
  const gate=$("webAuthGate"), msg=$("webAuthMessage");
  if(!gate)return;
  gate.classList.toggle("hidden",!show);
  document.body.classList.toggle("authLocked",show);
  if(msg&&message)msg.textContent=message;
  if(show)setTimeout(()=>$("webAuthSecret")?.focus(),60);
}
async function ensureWebAuth(){
  try{
    const health=await (await fetch(CORE_API+"/health",{cache:"no-store"})).json();
    if(!health.auth_required){setWebAuthGate(false);return true}
    const state=await (await fetch(CORE_API+"/owner/status",{headers:apiHeaders(),cache:"no-store"})).json();
    if(state.op_active){setWebAuthGate(false);return true}
    setWebAuthGate(true,"Connect this iPhone once. RONN will remember it across future updates.");
    return false;
  }catch{
    setWebAuthGate(true,"RONN Core is waking up or unavailable. Try again in a moment.");
    return false;
  }
}
async function unlockWebAuth(){
  const secret=$("webAuthSecret")?.value||"";
  if(!secret)return;
  const btn=$("webAuthUnlock"),msg=$("webAuthMessage");
  if(btn){btn.disabled=true;btn.textContent="Connecting…"}
  if(msg)msg.textContent="Connecting this device securely…";
  try{
    const r=await fetch(CORE_API+"/owner/unlock",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({secret,device_id:deviceId,device_name:"RONN Web",platform:navigator.platform||"web",app_version:"R19",return_token:false})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||"Could not connect this device.");
    $("webAuthSecret").value="";
    setWebAuthGate(false);
    await refreshStatus();
    await refreshMemory();
    refreshOwnerAccess();
    refreshRobloxStudio();
    setTimeout(maybeRunBrainArena,1200);
  }catch(e){if(msg)msg.textContent=e.message||"Could not unlock RONN."}
  finally{if(btn){btn.disabled=false;btn.textContent="Continue"}}
}

const CHAT_KEY="ronnChats", CURRENT_KEY="ronnCurrentChat", PROJECT_KEY="ronnProjects", ACTIVE_PROJECT_KEY="ronnActiveProject", OUTCOME_KEY="ronnOutcomeProfileR23", ARENA_KEY="ronnBrainArenaR23";
function outcomeSnapshot(){
  const raw=loadJSON(OUTCOME_KEY,{version:"R23-OUTCOME-1",rows:[]});
  const rows=Array.isArray(raw?.rows)?raw.rows:[];
  return {version:"R23-OUTCOME-1",rows:rows.slice(0,40).map(x=>({
    model:String(x.model||"").slice(0,220),
    profile:String(x.profile||"").slice(0,40),
    good:Math.max(0,Math.min(100,Number(x.good||0)|0)),
    bad:Math.max(0,Math.min(100,Number(x.bad||0)|0)),
    updated:Number(x.updated||0)
  })).filter(x=>x.model&&x.profile)}
}
function recordOutcome(model,profile,rating){
  model=String(model||"").trim().slice(0,220);
  profile=String(profile||"").trim().toLowerCase().slice(0,40);
  if(!model||!profile||![1,-1].includes(Number(rating)))return;
  const data=outcomeSnapshot();
  let row=data.rows.find(x=>x.model===model&&x.profile===profile);
  if(!row){row={model,profile,good:0,bad:0,updated:0};data.rows.push(row)}
  const total=Number(row.good||0)+Number(row.bad||0);
  if(total>=24){row.good=Math.floor(Number(row.good||0)/2);row.bad=Math.floor(Number(row.bad||0)/2)}
  if(Number(rating)>0)row.good=Math.min(100,Number(row.good||0)+1);
  else row.bad=Math.min(100,Number(row.bad||0)+1);
  row.updated=Date.now();
  data.rows.sort((a,b)=>Number(b.updated||0)-Number(a.updated||0));
  data.rows=data.rows.slice(0,40);
  saveJSON(OUTCOME_KEY,data);
}

function migrateLocalStorage(){
  const pairs=[["novaUltraChats",CHAT_KEY],["novaUltraCurrentChat",CURRENT_KEY],["novaUltraProjects",PROJECT_KEY],["novaUltraActiveProject",ACTIVE_PROJECT_KEY]];
  for(const [oldKey,newKey] of pairs){if(safeGet(newKey)==null&&safeGet(oldKey)!=null)safeSet(newKey,safeGet(oldKey));}
}
migrateLocalStorage();

let pending=[],busy=false,controller=null,currentView="chat",startedAt=0,activityTimer=null,currentRequestId="",streamFollowLatest=true;
let screenStream=null,screenVideo=null,voiceMode=false,voiceSpeaking=false;
let chats=loadJSON(CHAT_KEY,[]),currentChatId=safeGet(CURRENT_KEY)||"",projects=loadJSON(PROJECT_KEY,[]),editingProjectId=null;

function loadJSON(k,f){try{return JSON.parse(safeGet(k))??f}catch{return f}}
function saveJSON(k,v){safeSet(k,JSON.stringify(v))}
function uid(p){return p+"-"+Date.now()+"-"+Math.random().toString(36).slice(2,8)}
function escapeHTML(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
function sanitizeVisible(s){return String(s||"").replace(/<think>[\s\S]*?<\/think>/gi,"").replace(/<\/?think>/gi,"").replace(/\\\|/g,"|").replace(/\\<(ul|li|br|table|tr|td|th)>/gi,"<$1>")}
function looksInternalToolPayload(s,userText=""){
  const raw=String(s||"").trim(),low=raw.toLowerCase(),u=String(userText||"").toLowerCase();
  const named=["groq_web_search","web_search","visit_website","browser.search","browser.open","searxng","crawl4ai"].some(x=>low.includes(x));
  const protocol=(low.includes('"tool"')||low.includes("'tool'")||low.includes("tool_call"))&&(low.includes('"args"')||low.includes("'args'")||low.includes('"arguments"')||low.includes("'arguments'"));
  const wantsJSON=["return json","return only json","give me json","output json","respond in json","json object","json array","show me the search queries","give me search queries","list the search queries"].some(x=>u.includes(x));
  let planner=false;
  if(!wantsJSON&&(raw.startsWith("{")||raw.startsWith("```json"))){
    let candidate=raw.replace(/^\s*```(?:json)?\s*/i,"").replace(/\s*```\s*$/i,"").trim();
    try{
      const obj=JSON.parse(candidate),keys=obj&&typeof obj==="object"&&!Array.isArray(obj)?Object.keys(obj).map(k=>String(k).toLowerCase()):[];
      const plannerKeys=["queries","search_queries","searches","query_plan","search_plan","search_query","urls","search_urls"];
      const allowed=new Set([...plannerKeys,"reason","intent","topic","limit"]);
      planner=keys.some(k=>plannerKeys.includes(k))&&keys.length>0&&keys.every(k=>allowed.has(k));
    }catch{}
  }
  return (raw.startsWith("{")||raw.startsWith("[")||raw.startsWith("```json"))&&(protocol||named||planner);
}
function inline(s){s=escapeHTML(s);s=s.replace(/`([^`]+)`/g,"<code>$1</code>");s=s.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");s=s.replace(/\*([^*\n]+)\*/g,"<em>$1</em>");s=s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');return s}
function isTableSep(line){return /^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$/.test(line)}
function splitTable(line){return line.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(x=>inline(x.trim()))}
function renderMarkdown(raw){
  let text=sanitizeVisible(raw).replace(/<(?:ul|\/ul)>/gi,"\n").replace(/<li>/gi,"- ").replace(/<\/li>/gi,"\n").replace(/<br\s*\/?>/gi,"\n");
  const blocks=[];
  text=text.replace(/```([A-Za-z0-9_+#.-]*)\n?([\s\S]*?)```/g,(_,lang,code)=>{const i=blocks.length;blocks.push(`<div class="codeWrap"><div class="codeHead"><span>${escapeHTML(lang||"code")}</span><div class="codeActions"><button class="downloadCode">Download</button><button class="copyCode">Copy</button></div></div><pre><code>${escapeHTML(code.replace(/\n$/,"") )}</code></pre></div>`);return `\n@@CODE${i}@@\n`});
  const lines=text.split(/\r?\n/),out=[];let list=null;const close=()=>{if(list){out.push(list==="ol"?"</ol>":"</ul>");list=null}};
  for(let i=0;i<lines.length;i++){
    const line=lines[i];if(/^@@CODE\d+@@$/.test(line.trim())){close();out.push(line.trim());continue}
    if(i+1<lines.length&&line.includes("|")&&isTableSep(lines[i+1])){close();const h=splitTable(line);i+=2;const rows=[];while(i<lines.length&&lines[i].includes("|")&&lines[i].trim()){rows.push(splitTable(lines[i]));i++}i--;out.push('<div class="tableWrap"><table><thead><tr>'+h.map(x=>`<th>${x}</th>`).join("")+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+h.map((_,j)=>`<td>${r[j]||""}</td>`).join("")+'</tr>').join("")+'</tbody></table></div>');continue}
    let m=line.match(/^\s*(\d+)\.\s+(.+)/);if(m){if(list!=="ol"){close();out.push("<ol>");list="ol"}out.push(`<li>${inline(m[2])}</li>`);continue}
    m=line.match(/^\s*[-•]\s+(.+)/);if(m){if(list!=="ul"){close();out.push("<ul>");list="ul"}out.push(`<li>${inline(m[1])}</li>`);continue}
    close();m=line.match(/^(#{1,4})\s+(.+)/);if(m){const n=Math.min(4,m[1].length+1);out.push(`<h${n}>${inline(m[2])}</h${n}>`);continue}
    if(/^\s*>\s?/.test(line)){out.push(`<blockquote>${inline(line.replace(/^\s*>\s?/,""))}</blockquote>`);continue}
    if(/^\s*---+\s*$/.test(line)){out.push("<hr>");continue}if(line.trim())out.push(`<p>${inline(line)}</p>`);
  }close();let html=out.join("");blocks.forEach((b,i)=>html=html.replace(`@@CODE${i}@@`,b));return html;
}

function currentChat(){let c=chats.find(x=>x.id===currentChatId);if(!c){c={id:uid("chat"),title:"New chat",messages:[],created:Date.now(),updated:Date.now()};chats.unshift(c);currentChatId=c.id;safeSet(CURRENT_KEY,currentChatId);saveChats()}return c}
function saveChats(){saveJSON(CHAT_KEY,chats.slice(0,100));renderChatList()}
function autoTitle(t){return (t||"New chat").replace(/\s+/g," ").trim().slice(0,46)||"New chat"}
function renderChatList(){const q=$("chatSearch").value.toLowerCase().trim(),list=$("chatList");list.innerHTML="";$("chatCount").textContent=chats.length;chats.filter(c=>!q||c.title.toLowerCase().includes(q)).slice(0,10).forEach(c=>{const row=document.createElement("button");row.className="chatRow"+(c.id===currentChatId?" active":"");row.innerHTML=`<span>${escapeHTML(c.title)}</span><b data-del="${c.id}" title="Delete">×</b>`;row.onclick=e=>{if(e.target.dataset.del){e.stopPropagation();if(c.coreConversationId){fetch(CORE_API+`/conversations/${encodeURIComponent(c.coreConversationId)}`,{method:"DELETE",headers:apiHeaders()}).catch(()=>{})}chats=chats.filter(x=>x.id!==c.id);if(currentChatId===c.id)currentChatId="";saveChats();renderMessages();return}if(currentChatId===c.id){showView("chat");return}currentChatId=c.id;safeSet(CURRENT_KEY,currentChatId);renderMessages();renderChatList();showView("chat")};list.appendChild(row)})}
function auditWarnings(a){return [...(a?.warnings||[]),...(a?.r5_quality_gate?.warnings||[]),...(a?.r7_quality?.warnings||[])].filter((x,i,arr)=>arr.indexOf(x)===i)}
function auditLabel(a){if(!a)return "";const warnings=auditWarnings(a).length;if(warnings)return `Review · ${warnings} flag${warnings===1?"":"s"}`;if(a.evidence_mode==="live")return "Live evidence route";const score=Number.isFinite(a?.r7_quality?.score)?a.r7_quality.score:a?.r5_quality_gate?.quality_score;return a.runtime_verified?"Runtime verified":Number.isFinite(score)?`Audited · ${score}`:"Answer audited"}
function applyAudit(wrap,a){if(!wrap||!a)return;let chip=wrap.querySelector(".auditChip");if(!chip){chip=document.createElement("span");chip.className="auditChip";const tools=wrap.querySelector(".msgTools");if(tools)tools.prepend(chip)}const warnings=auditWarnings(a);chip.textContent=auditLabel(a);chip.className="auditChip "+(warnings.length?"warn":"ok");chip.title=warnings.length?warnings.join(" • "):`Evidence: ${a.evidence_mode||"model"}; runtime verified: ${a.runtime_verified?"yes":"no"}`}
function renderMetaCards(meta){
  const hub=meta?.tool_hub||{},p=hub.presentation||null,sources=Array.isArray(hub.sources)?hub.sources:[];
  let html="";
  if(p?.type==="weather"){
    const temp=p.temperature_f==null?"—":Math.round(Number(p.temperature_f));
    const feels=p.feels_like_f==null?"—":Math.round(Number(p.feels_like_f));
    const wind=p.wind_mph==null?"—":Math.round(Number(p.wind_mph));
    html+=`<div class="richCard weatherCard"><div><small>WEATHER</small><b>${escapeHTML(p.location||"Current weather")}</b></div><strong>${escapeHTML(String(temp))}°F</strong><p>${escapeHTML(p.condition||"Current conditions")} · Feels like ${escapeHTML(String(feels))}° · Wind ${escapeHTML(String(wind))} mph</p></div>`;
  }
  if(sources.length){
    const unique=[];const seen=new Set();
    for(const s of sources){const u=String(s?.url||"");if(!u||seen.has(u))continue;seen.add(u);unique.push(s);if(unique.length>=5)break}
    if(unique.length)html+=`<div class="sourceCards"><span>Sources</span>${unique.map(s=>`<a href="${escapeHTML(s.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(s.title||new URL(s.url).hostname)}</a>`).join("")}</div>`;
  }
  return html?'<div class="richCards">'+html+'</div>':"";
}
function applyMetaCards(wrap,meta){
  if(!wrap||!meta)return;
  const bubble=wrap.querySelector(".aiBubble"); if(!bubble)return;
  bubble.querySelector(".richCards")?.remove();
  const html=renderMetaCards(meta); if(!html)return;
  const tools=bubble.querySelector(".msgTools");
  if(tools)tools.insertAdjacentHTML("beforebegin",html);
}
function addMessageNode(role,text,requestId="",audit=null,meta=null){const wrap=document.createElement("div");wrap.className="message "+role;if(role==="assistant"){wrap.dataset.requestId=requestId||"";wrap.dataset.model=meta?.model||"";wrap.dataset.profile=meta?.profile||"";wrap.innerHTML=`<div class="aiMark"><img src="/static/ronn_logo.svg" alt="RONN"></div><div class="bubble aiBubble"><div class="answer">${renderMarkdown(text)}</div>${renderMetaCards(meta)}<div class="msgTools"><button class="copyMsg">Copy</button><button class="verifyMsg">Verify</button><button class="retryMsg">Retry</button>${meta?.decision_summary?'<button class="whyMsg">Why</button>':""}${requestId?'<button class="rateMsg" data-rating="1">Good</button><button class="rateMsg" data-rating="-1">Improve</button>':""}</div></div>`;if(meta?.decision_summary)wrap.dataset.decision=meta.decision_summary.summary||"";if(audit)applyAudit(wrap,audit)}else wrap.innerHTML=`<div class="bubble userBubble">${escapeHTML(text)}</div>`;messages.appendChild(wrap);return wrap}
function welcome(){messages.innerHTML=`<div class="welcome"><div class="welcomeOrb"><span>R</span></div><h1>How can I help?</h1><p>Ask RONN anything, attach a project, or start with one of these.</p><div class="capGrid"><button data-prompt="Create this for me from start to finish. Keep it clean, functional, and verify what you can."><b>Create</b><span>Build something</span></button><button data-prompt="Research this using current reliable information and clearly separate verified facts from uncertainty."><b>Research</b><span>Use current evidence</span></button><button data-prompt="Solve this coding problem. Find the root cause, implement the fix, and run available checks before saying it works."><b>Code</b><span>Build + test</span></button><button data-prompt="Analyze this deeply, compare the important possibilities, and give me the clearest useful result."><b>Analyze</b><span>Think it through</span></button></div></div>`;bindPromptButtons()}
function nearBottom(){return messages.scrollHeight-messages.scrollTop-messages.clientHeight<120}
function updateJumpLatest(){if(!jumpLatest)return;const show=messages.scrollHeight>messages.clientHeight+40&&!nearBottom();jumpLatest.classList.toggle("hidden",!show)}
function scrollToLatest(force=false){if(force||nearBottom()){messages.scrollTop=messages.scrollHeight;requestAnimationFrame(()=>{messages.scrollTop=messages.scrollHeight;updateJumpLatest()})}else updateJumpLatest()}
function renderMessages(){messages.innerHTML="";const c=currentChat();if(!c.messages.length){welcome();requestAnimationFrame(()=>updateJumpLatest());return}c.messages.forEach(m=>addMessageNode(m.role,m.content,m.requestId||"",m.audit||null,m.meta||null));requestAnimationFrame(()=>scrollToLatest(true))}
function pushMessage(role,content,requestId="",audit=null,meta=null){const c=currentChat();if(c.messages.length===0&&role==="user")c.title=autoTitle(content);c.messages.push({role,content,requestId,audit,meta});c.updated=Date.now();saveChats()}
function bindPromptButtons(){qsa("[data-prompt]").forEach(b=>b.onclick=()=>{input.value=b.dataset.prompt;autoSize();input.focus()})}
function setStage(x){stageBadge.textContent=x;stageBadge.dataset.stage=String(x||"").toLowerCase();if(busy)updateActivity(x)}
function setNeuralMeta(meta){const n=$("neuralBadge");if(!n||!meta)return;const d=meta.difficulty??0,t=String(meta.adaptive_tier||meta.controller?.depth||"smart");let label="R22 · "+({fast:"Fast",smart:"Smart",deep:"Deep",apex:"Apex"}[t]||"Smart");if(meta.verification_level==="high")label+=" · Verify";if(["live","research","max","tools"].includes(meta.route))label="R22 · Live";n.textContent=label;n.classList.toggle("hot",t==="deep"||t==="apex"||meta.verification_level==="high")}
function routeLabel(x){return ({instant:"Instant",fast:"Fast",deep:"Deep brain",creator:"Code specialist",roblox:"Roblox Studio",max:"Research",ultra:"Deep brain",apex:"Apex brain",knowledge:"Main brain",live:"Live web",research:"Research",vision:"Vision",review:"Verified",backup:"Fallback","nvidia-apex":"Apex brain","nvidia-apex-final":"Apex synthesis","apex-final":"Apex synthesis","nvidia-ultra-final":"Deep synthesis","ultra-final":"Deep synthesis","local-tool":"Local tool",memory:"Memory"})[x]||x||"Auto"}
function profileLabel(x){return ({coding:"Software",roblox:"Roblox Studio",creative:"Creative",research:"Research",analysis:"Analysis",knowledge:"Knowledge",mathscience:"Math & science",writing:"Writing",chat:"General",memory:"Memory"})[x]||x||"General"}
function autoSize(){input.style.height="auto";const cap=window.innerWidth<=780?144:180;input.style.height=Math.min(input.scrollHeight,cap)+"px";if(window.innerWidth<=780&&document.activeElement===input){syncMobileViewport();requestAnimationFrame(()=>scrollToLatest(true))}}

async function currentScreenFrame(){
  if(!screenStream||!screenVideo||screenVideo.readyState<2)return null;
  const w=screenVideo.videoWidth||1280,h=screenVideo.videoHeight||720;if(!w||!h)return null;
  const max=1400,scale=Math.min(1,max/w),cw=Math.max(1,Math.round(w*scale)),ch=Math.max(1,Math.round(h*scale));
  const canvas=document.createElement("canvas");canvas.width=cw;canvas.height=ch;
  const ctx=canvas.getContext("2d");ctx.drawImage(screenVideo,0,0,cw,ch);
  return canvas.toDataURL("image/jpeg",0.72);
}
function stopScreenContext(){
  if(screenStream){screenStream.getTracks().forEach(t=>t.stop())}
  screenStream=null;screenVideo=null;
  const b=$("screenBtn");if(b){b.classList.remove("active");b.textContent="▣";b.title="Share your screen as live chat context"}
}
async function toggleScreenContext(){
  if(screenStream){stopScreenContext();showToast("Screen context off.");return}
  if(!navigator.mediaDevices?.getDisplayMedia){showToast("Screen sharing is not supported by this browser.");return}
  try{
    screenStream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:{ideal:5,max:10}},audio:false});
    screenVideo=document.createElement("video");screenVideo.srcObject=screenStream;screenVideo.muted=true;screenVideo.playsInline=true;await screenVideo.play();
    const track=screenStream.getVideoTracks()[0];if(track)track.onended=()=>stopScreenContext();
    const b=$("screenBtn");if(b){b.classList.add("active");b.textContent="■";b.title="Screen context is active"}
    showToast("Screen context on. RONN will see the latest frame when you send a message.");
  }catch(e){stopScreenContext();if(e?.name!=="NotAllowedError")showToast("Screen share could not start.")}
}

function renderAttachments(){attachmentsEl.innerHTML="";pending.forEach((a,i)=>{const el=document.createElement("div");el.className="attachment";el.innerHTML=a.kind==="image"?`<img src="${a.data}"><span>${escapeHTML(a.name)}</span>`:`<div class="fileIcon">{ }</div><span>${escapeHTML(a.name)}</span>`;const x=document.createElement("button");x.textContent="×";x.onclick=()=>{pending.splice(i,1);renderAttachments()};el.appendChild(x);attachmentsEl.appendChild(el)})}
const textExt=/\.(txt|md|py|js|ts|tsx|jsx|lua|luau|json|html|css|csv|xml|yaml|yml)$/i,docExt=/\.(pdf|docx|xlsx|pptx)$/i;
const MAX_IMAGE_BYTES=20*1024*1024,MAX_DOCUMENT_BYTES=25*1024*1024,MAX_CHAT_IMAGE_RAW_BYTES=22*1024*1024;
function pendingImageBytes(){return pending.reduce((n,a)=>n+(a?.kind==="image"?Number(a.bytes||0):0),0)}
function addFiles(files){let imageBytes=pendingImageBytes();[...files].slice(0,8).forEach(file=>{if(file.type.startsWith("image/")){if(file.size>MAX_IMAGE_BYTES)return showToast("Image is over 20 MB.");if(imageBytes+file.size>MAX_CHAT_IMAGE_RAW_BYTES)return showToast("Images together must stay under 22 MB.");imageBytes+=file.size;const r=new FileReader();r.onload=()=>{pending.push({kind:"image",name:file.name,data:r.result,bytes:file.size});renderAttachments()};r.readAsDataURL(file)}else if(docExt.test(file.name)){if(file.size>MAX_DOCUMENT_BYTES)return showToast("Document is over 25 MB.");const r=new FileReader();r.onload=async()=>{try{showToast("Extracting "+file.name+"…");const resp=await fetch("/api/document/extract",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({filename:file.name,data:r.result})});const d=await resp.json();if(!resp.ok)throw new Error(d.detail||"Document extraction failed.");pending.push({kind:"text",name:file.name,content:String(d.text||"").slice(0,80000)});renderAttachments();showToast("Document ready.")}catch(e){showToast(e.message)}};r.readAsDataURL(file)}else if(textExt.test(file.name)){if(file.size>4*1024*1024)return showToast("Text/code files must be under 4 MB.");const r=new FileReader();r.onload=()=>{pending.push({kind:"text",name:file.name,content:String(r.result).slice(0,80000)});renderAttachments()};r.readAsText(file)}else showToast("RONN accepts images, code/text, PDF, DOCX, XLSX, and PPTX files.")})}

function activeProject(){const id=safeGet(ACTIVE_PROJECT_KEY)||"";return projects.find(p=>p.id===id)||null}
function composeActiveProjectContext(){const p=activeProject();if(!p)return "";const name=String(p.name||"").trim(),ctx=String(p.context||"").trim();return [name?"Project: "+name:"",ctx].filter(Boolean).join("\n")}
async function refreshActiveProjectBrain(){
  const p=activeProject();if(!p?.coreProjectId)return;
  try{
    const r=await fetch("/api/r23/project-brain/export?project_id="+encodeURIComponent(p.coreProjectId),{headers:apiHeaders(),cache:"no-store"});
    if(!r.ok)return;
    const d=await r.json();
    if(d?.snapshot&&typeof d.snapshot==="object"){
      p.brainSnapshot=d.snapshot;
      p.brainStats=d.stats||{};
      p.brainSnapshotAt=Date.now();
      saveJSON(PROJECT_KEY,projects);
    }
  }catch{}
}
function updateProjectBadge(){const p=activeProject(),b=$("projectBadge");b.textContent=p?p.name:"No project";b.classList.toggle("active",!!p);$("activeProjectDot").classList.toggle("on",!!p)}

function startActivity(){startedAt=Date.now();$("activityDock").classList.remove("hidden");$("activityTitle").textContent="RONN is working";$("activityDetail").textContent="Understanding the request and choosing a reliable route.";clearInterval(activityTimer);activityTimer=setInterval(()=>{$("activityTime").textContent=Math.floor((Date.now()-startedAt)/1000)+"s"},1000)}
function updateActivity(stage){const map={Planning:"Understanding requirements",Researching:"Checking live information and evidence",Council:"Comparing independent solution paths","Deep reasoning":"Working through a harder reasoning route",Thinking:"Checking the answer","Analyzing":"Analyzing attached content",Building:"Constructing the response",Drafting:"Creating a first solution",Reviewing:"Critiquing and repairing the draft","Parallel hypotheses":"Exploring independent approaches","Adversarial synthesis":"Checking candidates for defects","Specialist draft":"Building a specialist solution","Final synthesis":"Repairing and consolidating the final answer","Inspect evidence":"Connecting screenshots, files, logs, and project context","Reproduce or isolate failure":"Isolating the failure before changing anything","Rank root causes":"Comparing likely causes against the evidence","Apply smallest safe repair":"Choosing a reversible root-cause repair","Verify":"Checking requirements, evidence, and regressions","Studio state":"Reading the selected Roblox Studio state","Studio inspect":"Inspecting the existing Roblox project before changing it","Studio edit":"Applying the smallest safe Studio change","Studio verify":"Play-testing the change and checking Output","Studio repair":"Repairing a failed Studio verification","Studio cleanup":"Returning Studio to a clean test state","Deliver":"Preparing the final verified result"};$("activityDetail").textContent=map[stage]||String(stage||"Working")}
function stopActivity(){clearInterval(activityTimer);activityTimer=null;setTimeout(()=>$("activityDock").classList.add("hidden"),500)}

let ronnLocationCache=null,ronnLocationAt=0;
function needsRONNLocation(text){
  return /\b(near me|nearby|closest|around me|close to me|in my area|my location|use my location|see my location|current location|where am i|restaurants? near|restaurants? around|food near|places? to eat near|coffee near|gas stations? near|stores? near|pharmacy near|hospital near|open near me|recommend(?: me)? restaurants?)\b/i.test(String(text||""))
}
async function getRONNLocation(text){
  if(!needsRONNLocation(text)||!navigator.geolocation)return null;
  if(ronnLocationCache&&Date.now()-ronnLocationAt<10*60*1000)return ronnLocationCache;
  setStage("Location");
  return await new Promise(resolve=>navigator.geolocation.getCurrentPosition(
    pos=>{
      ronnLocationCache={latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy:pos.coords.accuracy};
      ronnLocationAt=Date.now();
      resolve(ronnLocationCache)
    },
    ()=>resolve(null),
    {enableHighAccuracy:false,timeout:7000,maximumAge:5*60*1000}
  ))
}

async function sendMessage(regenerate=false,overrideText=null){
  if(busy)return;
  const text=overrideText??(regenerate?(currentChat().messages.filter(m=>m.role==="user").at(-1)?.content||""):input.value.trim());if(!text&&!pending.length)return;
  busy=true;streamFollowLatest=true;controller=new AbortController();sendBtn.classList.add("hidden");stopBtn.classList.remove("hidden");setStage("Planning");startActivity();
  const atts=[...pending];const sharedFrame=await currentScreenFrame();if(sharedFrame)atts.push({kind:"image",name:"Live screen",data:sharedFrame,screen:true});if(!regenerate&&overrideText==null){pending=[];renderAttachments();input.value="";autoSize()}
  const c=currentChat(),history=c.messages.slice(-36).map(m=>({role:m.role,content:m.content}));if(!regenerate&&overrideText==null){pushMessage("user",text||"[Attachment]");addMessageNode("user",text||"[Attachment]")}
  const ai=addMessageNode("assistant","");const answerEl=ai.querySelector(".answer");answerEl.innerHTML='<span class="thinkingDots"><i></i><i></i><i></i></span>';scrollToLatest(true);
  let answer="",first=true,responseRequestId="",responseAudit=null,responseMeta=null;
  try{
    const clientLocation=await getRONNLocation(text);
    const res=await fetch(CORE_API+"/chat",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),signal:controller.signal,body:JSON.stringify({message:text,conversation_id:currentChat().coreConversationId||null,project_id:activeProject()?.coreProjectId||"default",history,images:atts.filter(a=>a.kind==="image").map(a=>a.data),files:atts.filter(a=>a.kind==="text").map(a=>({name:a.name,content:a.content})),mode:$("modeSelect").value,style:$("styleSelect").value,project_context:composeActiveProjectContext(),review:$("reviewToggle").checked,agent_mode:$("agentToggle")?.checked!==false,skill_profile:"auto",client_location:clientLocation||{},project_brain_snapshot:activeProject()?.brainSnapshot||{},outcome_profile:outcomeSnapshot()})});
    if(!res.ok){const d=await res.json().catch(()=>({}));if(res.status===401){setWebAuthGate(true,"This device needs to reconnect to RONN.");throw new Error("RONN needs to reconnect this device.")}throw new Error(d.detail||`RONN server returned HTTP ${res.status}.`)}
    const reader=res.body.getReader(),decoder=new TextDecoder();let buffer="";
    while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const lines=buffer.split("\n");buffer=lines.pop();for(const line of lines){if(!line.trim())continue;let d;try{d=JSON.parse(line)}catch{continue}if(d.core?.conversation_id){const cc=currentChat();cc.coreConversationId=d.core.conversation_id;saveChats();continue}if(d.meta){responseMeta=d.meta;ai.dataset.model=d.meta.model||ai.dataset.model||"";ai.dataset.profile=d.meta.profile||ai.dataset.profile||"";responseRequestId=d.meta.request_id||responseRequestId;currentRequestId=responseRequestId||currentRequestId;routeBadge.textContent=routeLabel(d.meta.route);profileBadge.textContent=profileLabel(d.meta.profile);setNeuralMeta(d.meta);if(d.meta.task_plan?.checkpoint_count){$("activityTitle").textContent=`RONN · ${d.meta.task_plan.checkpoint_count} checkpoints`}if(d.meta.adaptive_tier){$("activityDetail").textContent=`Adaptive tier: ${d.meta.adaptive_tier} · verifying requirements and evidence boundaries.`}const warnings=d.meta.r7_preflight?.agent_plan?.risk?.proactive_warnings||[];if(warnings.length)$("activityDetail").textContent=warnings[0];const stage=["live","research","max","tools"].includes(d.meta.route)?"Researching":String(d.meta.route||"").includes("ultra")?"Council":String(d.meta.route||"").startsWith("nvidia")?"Deep reasoning":d.meta.route==="knowledge"?"Thinking":d.meta.route==="vision"?"Analyzing":"Building";setStage(stage)}if(d.stage)setStage(d.stage);if(d.done&&d.audit)responseAudit=d.audit;if(d.error)throw new Error(d.error);if(d.token){if(first)first=false;answer=sanitizeVisible(answer+d.token);if(looksInternalToolPayload(answer,text)){answerEl.innerHTML='<span class="thinkingDots"><i></i><i></i><i></i></span>';continue}answerEl.innerHTML=renderMarkdown(answer)+'<span class="cursor">▌</span>';scrollToLatest(streamFollowLatest)}}}
    answer=sanitizeVisible(answer).trim();if(looksInternalToolPayload(answer,text))throw new Error("RONN blocked an internal tool command instead of showing it. Retry the question.");if(!answer)throw new Error("The provider returned no usable answer. RONN did not fabricate one.");answerEl.innerHTML=renderMarkdown(answer);applyMetaCards(ai,responseMeta);scrollToLatest(streamFollowLatest);if(responseAudit)applyAudit(ai,responseAudit);pushMessage("assistant",answer,responseRequestId,responseAudit,responseMeta);if(voiceMode)speakRONN(answer);ai.dataset.requestId=responseRequestId||"";if(responseRequestId){const tools=ai.querySelector(".msgTools");if(tools&&!tools.querySelector(".rateMsg"))tools.insertAdjacentHTML("beforeend",'<button class="rateMsg" data-rating="1">Good</button><button class="rateMsg" data-rating="-1">Improve</button>')}setStage("Complete");refreshMemory();refreshActiveProjectBrain()
  }catch(e){if(e.name==="AbortError"){answerEl.innerHTML=renderMarkdown(answer||"Stopped.");setStage("Stopped")}else{answerEl.innerHTML=`<p><strong>Error:</strong> ${escapeHTML(e.message)}</p><p>Open <strong>Diagnostics</strong> if this keeps happening.</p>`;setStage("Error")}}
  finally{busy=false;controller=null;currentRequestId="";stopBtn.classList.add("hidden");sendBtn.classList.remove("hidden");stopActivity();setTimeout(()=>setStage("Ready"),1500);if(window.innerWidth>780)input.focus()}
}

function showToast(text){const t=$("toast");t.textContent=text;t.classList.add("show");clearTimeout(showToast._t);showToast._t=setTimeout(()=>t.classList.remove("show"),2700)}
function showView(name){
  const target=$(name+"View");
  if(!target)return;
  const family=(name==="memory"||name==="projects")?"projects":(name==="diagnostics"||name==="brain")?"brain":name;
  const alreadyActive=currentView===name&&target.classList.contains("active");
  qsa(".navBtn").forEach(b=>b.classList.toggle("active",b.dataset.view===family));
  qsa("[data-view-target]").forEach(b=>b.classList.toggle("active",b.dataset.viewTarget===name));
  const pm=$("plusMenu");if(pm)pm.classList.add("hidden");
  if(alreadyActive)return;
  currentView=name;
  qsa(".view").forEach(v=>v.classList.remove("active"));
  target.classList.add("active");
  if(name==="memory")refreshMemory();
  if(name==="projects")renderProjects();
  if(name==="brain"){refreshBrain();refreshAgentOps()}
  if(name==="diagnostics")runDiagnostics();
  if(name==="settings"){refreshOwnerAccess();refreshEcosystemStatus();refreshR19Capabilities()}
}

async function refreshStatus(){try{const r=await fetch(CORE_API+"/status",{headers:apiHeaders()});if(!r.ok)throw new Error();const d=await r.json();const buildOk=d.build===BUILD_EXPECTED;$("statusDot").classList.toggle("on",buildOk);$("buildText").textContent=d.build||"RONN";$("serverStatus").textContent=buildOk?"Exact build verified":"Build mismatch";$("memoryCount").textContent=d.memory_count??0;const any=d.api_key_loaded,p=$("providerBadge");p.textContent=d.groq_key_loaded?"Groq configured":d.nvidia_key_loaded?"NVIDIA configured":"No AI key";p.className="providerBadge "+(any?"ok":"warn");$("diagnosticDot").className=buildOk&&d.internal_eval_score===100&&d.r5_eval_score===100&&d.r6_eval_score===100&&d.r7_eval_score===100&&d.r11_eval_score===100&&d.r12_eval_score===100&&d.r13_eval_score===100&&d.r14_eval_score===100&&d.r15_eval_score===100&&d.r23_eval_score===100&&d.r23_all_11_ready===true?"good":"on"}catch{$("serverStatus").textContent="Server unavailable";$("statusDot").classList.remove("on")}}
async function refreshMemory(){try{const d=await (await fetch(CORE_API+"/memory",{headers:apiHeaders()})).json();$("memoryCount").textContent=d.memories.length;const list=$("memoryList");list.innerHTML="";if(!d.memories.length){list.innerHTML='<div class="emptyState">No saved memories yet.</div>';return}d.memories.forEach(m=>{const row=document.createElement("div");row.className="memoryItem";row.innerHTML=`<div class="memoryMain"><span>${escapeHTML(m.text)}</span><small>${escapeHTML(m.category||"general")} · ${Math.round(Number(m.confidence||.8)*100)}% confidence${m.use_count?` · used ${m.use_count}×`:""}</small></div><div class="memoryActions"><button class="pinMemory ${m.pinned?"active":""}" title="${m.pinned?"Unpin":"Pin"}">${m.pinned?"◆":"◇"}</button><button class="deleteMemory" title="Forget">×</button></div>`;row.querySelector(".deleteMemory").onclick=async()=>{await fetch(CORE_API+`/memory/${m.id}`,{method:"DELETE",headers:apiHeaders()});refreshMemory();refreshStatus()};row.querySelector(".pinMemory").onclick=async()=>{await fetch(CORE_API+`/memory/${m.id}`,{method:"PATCH",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({pinned:!m.pinned})});refreshMemory()};list.appendChild(row)})}catch{}}

function renderProjects(){const grid=$("projectGrid");grid.innerHTML="";const active=activeProject();if(!projects.length){grid.innerHTML='<div class="emptyState big">Create a project to keep architecture, names, constraints, visual language, and known failures consistent.</div>';return}projects.forEach(p=>{const card=document.createElement("button");card.className="projectCard"+(active?.id===p.id?" active":"");card.innerHTML=`<div><b>${escapeHTML(p.name)}</b><span>${active?.id===p.id?"ACTIVE":"PROJECT"}</span></div><p>${escapeHTML((p.context||"").slice(0,180))}</p>`;card.onclick=()=>{safeSet(ACTIVE_PROJECT_KEY,p.id);updateProjectBadge();renderProjects();openProject(p.id)};grid.appendChild(card)})}
function openProject(id){const p=projects.find(x=>x.id===id);if(!p)return;editingProjectId=id;$("projectName").value=p.name;$("projectContext").value=p.context||"";$("projectEditor").classList.remove("hidden");$("projectGrid").classList.add("dim")}
function closeProjectEditor(){$("projectEditor").classList.add("hidden");$("projectGrid").classList.remove("dim");editingProjectId=null}


async function refreshBrain(){try{const d=await (await fetch("/api/tasks?limit=8",{headers:apiHeaders()})).json();const stats=d.stats||{};const statEl=$("taskEngineStats"),list=$("taskHistory");if(statEl)statEl.textContent=`${stats.completed||0} completed · ${stats.checkpoints||0} checkpoints`;if(!list)return;const rows=d.tasks||[];if(!rows.length){list.innerHTML='<div class="emptyState">No task runs recorded yet.</div>';return}list.innerHTML=rows.map(t=>`<div class="taskRun" title="${escapeHTML(t.task_id||"")}"><b>${escapeHTML((t.prompt||"Task").replace(/\s+/g," ").slice(0,100))}</b><span>${escapeHTML(t.profile||"general")} · D${Number(t.difficulty||0)}</span><i class="${escapeHTML(t.status||"")}">${escapeHTML(t.status||"unknown")}</i></div>`).join("")}catch(e){const list=$("taskHistory");if(list)list.innerHTML='<div class="emptyState">Task history is unavailable.</div>'}}
async function refreshAgentOps(){try{const q=await (await fetch(CORE_API+"/tasks",{headers:apiHeaders()})).json();const list=$("queueList");if(list){const rows=q.tasks||[];list.innerHTML=rows.length?rows.slice(0,12).map(x=>`<div class="agentOpRow"><div><b>${escapeHTML(x.title||"Task")}</b><small>${escapeHTML((x.prompt||"").slice(0,110))}</small></div><div><i>${escapeHTML(x.status||"queued")}</i>${["queued","running"].includes(x.status)?`<button data-queue-done="${x.id}">Done</button>`:""}</div></div>`).join(""):'<div class="emptyState">No queued work.</div>'}}catch{} }
async function addQueueItem(){const prompt=$("queueInput")?.value.trim();if(!prompt)return;const p=activeProject();await fetch(CORE_API+"/tasks",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({title:prompt.slice(0,70),prompt,project_id:p?.coreProjectId||"default",priority:50})});$("queueInput").value="";refreshAgentOps();showToast("Task queued.")}
async function searchKnowledge(){const q=$("kbSearchInput")?.value.trim();if(!q)return;const p=activeProject();const corePid=p?.coreProjectId||"default";const url=`${CORE_API}/projects/${encodeURIComponent(corePid)}/knowledge?q=${encodeURIComponent(q)}&limit=8`;const d=await (await fetch(url,{headers:apiHeaders()})).json();const el=$("kbResults"),rows=d.results||[];el.innerHTML=rows.length?rows.map(x=>`<div class="agentOpRow"><div><b>${escapeHTML(x.title||x.kind||"Knowledge")}</b><small>${escapeHTML((x.content||"").replace(/\s+/g," ").slice(0,150))}</small></div><i>${escapeHTML(x.kind||"item")}</i></div>`).join(""):'<div class="emptyState">No relevant indexed evidence found.</div>'}
function clientUiChecks(){const cs=getComputedStyle(messages),main=getComputedStyle(document.querySelector(".main")),chat=getComputedStyle($("chatView")),composer=getComputedStyle(document.querySelector(".composerDock"));const nativeFlow=window.innerWidth>780||((chat.display==="flex")&&(composer.position==="relative"||composer.position==="static"));return [
  ["UI · message scrolling",/auto|scroll/.test(cs.overflowY)&&messages.clientHeight>0?"Single scrollable message viewport":"Scroll ownership failed",/auto|scroll/.test(cs.overflowY)&&messages.clientHeight>0?"good":"bad"],
  ["UI · main overflow boundary",main.overflow==="hidden"||main.overflowY==="hidden"?"Stable app viewport":"Review app overflow",main.overflow==="hidden"||main.overflowY==="hidden"?"good":"warn"],
  ["UI · chat min-height",chat.minHeight==="0px"?"Flex/grid shrink enabled":`min-height ${chat.minHeight}`,chat.minHeight==="0px"?"good":"warn"],
  ["UI · mobile composer flow",nativeFlow?"Composer is in normal app flow":"Composer is overlapping chat",nativeFlow?"good":"bad"]
]}

async function runDiagnostics(){const s=$("diagnosticSummary");s.className="diagnosticSummary";s.innerHTML='<div class="diagSpinner"></div><span>Running local checks…</span>';try{const r=await fetch(CORE_API+"/diagnostics",{headers:apiHeaders()});const d=await r.json();$("diagBuild").textContent=d.build||"—";$("diagGroq").textContent=d.providers?.groq?.configured?"Configured":"Not configured";$("diagNvidia").textContent=d.providers?.nvidia?.configured?"Configured":"Optional / off";$("diagTests").textContent=`${(d.internal_eval?.passed??0)+(d.r5_eval?.passed??0)+(d.r6_eval?.passed??0)+(d.r7_eval?.passed??0)+(d.r11_eval?.passed??0)+(d.r12_eval?.passed??0)+(d.r13_eval?.passed??0)+(d.r14_eval?.passed??0)+(d.r15_eval?.passed??0)+(d.r23_eval?.passed??0)} / ${(d.internal_eval?.total??0)+(d.r5_eval?.total??0)+(d.r6_eval?.total??0)+(d.r7_eval?.total??0)+(d.r11_eval?.total??0)+(d.r12_eval?.total??0)+(d.r13_eval?.total??0)+(d.r14_eval?.total??0)+(d.r15_eval?.total??0)+(d.r23_eval?.total??0)} passed`;$("diagIntegrity").textContent=d.integrity?.verified?`${d.integrity.checked} files verified`:"Mismatch";$("diagTasks").textContent=`${d.task_engine?.completed??0} completed`;const exact=d.build===BUILD_EXPECTED,healthy=exact&&d.internal_eval?.score===100&&d.r5_eval?.score===100&&d.r6_eval?.score===100&&d.r7_eval?.score===100&&d.r11_eval?.score===100&&d.r12_eval?.score===100&&d.r13_eval?.score===100&&d.r14_eval?.score===100&&d.r15_eval?.score===100&&d.r23_eval?.score===100&&d.r23_all_11_ready===true&&!d.warnings?.filter(w=>!String(w).includes("integrity")).length;s.className="diagnosticSummary "+(healthy?"good":exact?"warn":"bad");s.innerHTML=`<span>${healthy?"Local runtime checks passed. Provider connectivity is tested separately.":exact?"RONN is running, but diagnostics found something to review.":"The browser is not connected to the expected RONN build."}</span>`;const rows=[];rows.push(["Runtime build",d.build,exact?"good":"bad"]);rows.push(["Core API",d.core_api?.api_version?`${d.core_api.api_version} · ${d.core_api.core_version}`:"Unavailable",d.core_api?.api_version==="v1"?"good":"bad"]);if(d.config){rows.push(["Provider key",d.config.provider_key_loaded?"Loaded":"Missing",d.config.provider_key_loaded?"good":"bad"]);rows.push(["Active .env",d.config.active_env||"Unknown",d.config.active_env_exists?"good":"bad"]);if(d.config.launcher_source)rows.push(["Config source",d.config.launcher_source,"good"]);if(d.config.shared_config)rows.push(["Persistent config",d.config.shared_config,"good"])}for(const row of clientUiChecks())rows.push(row);for(const [k,v] of Object.entries(d.files||{}))rows.push(["File · "+k,v?"Present":"Missing",v?"good":"bad"]);rows.push(["Package integrity",d.integrity?.verified?`${d.integrity.checked} core files match manifest`:`${d.integrity?.mismatches?.length||0} mismatch(es)`,d.integrity?.verified?"good":"bad"]);rows.push(["Task checkpoints",String(d.task_engine?.checkpoints??0),"good"]);for(const h of d.provider_health||[]){const rate=h.success_rate==null?"No samples":`${Math.round(h.success_rate*100)}% success · ${h.samples} samples`;rows.push([`Provider history · ${h.model}`,rate,h.consecutive_failures>=2?"warn":"good"])}for(const t of d.internal_eval?.tests||[])rows.push(["Core test · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);for(const t of d.r5_eval?.tests||[])rows.push(["R5 intelligence · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);for(const t of d.r6_eval?.tests||[])rows.push(["R6 adaptive · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);for(const t of d.r7_eval?.tests||[])rows.push(["R7 impact · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);for(const t of d.r11_eval?.tests||[])rows.push(["R11 reliability · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);rows.push(["R11 signal registry",String(d.r11_signal_registry||600)+" active signals","good"]);for(const t of d.r12_eval?.tests||[])rows.push(["R12 improvements · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);rows.push(["R12 improvement registry",String(d.r12_improvement_registry||400)+" active policies","good"]);for(const t of d.r13_eval?.tests||[])rows.push(["R13 ensemble · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);rows.push(["R13 ensemble",d.providers?.openrouter?.configured?"4 free specialists configured":"Ready for OpenRouter key",d.providers?.openrouter?.configured?"good":"warn"]);for(const t of d.r14_eval?.tests||[])rows.push(["R14 capability · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);rows.push(["R14 graph",`${d.r14_knowledge_graph?.nodes||0} nodes · ${d.r14_knowledge_graph?.edges||0} edges`,"good"]);for(const t of d.r15_eval?.tests||[])rows.push(["R15-R19 · "+t.name,t.passed?`Passed (${t.ms} ms)`:(t.error||"Failed"),t.passed?"good":"bad"]);for(const t of d.r23_eval?.tests||[])rows.push(["R23 · "+t.name,t.passed?"Passed":(t.error||"Failed"),t.passed?"good":"bad"]);rows.push(["R23 unified brain",d.r23_all_11_ready?"11 / 11 major capabilities passed":"R23 capability check incomplete",d.r23_all_11_ready?"good":"bad"]);const arena=d.r23_brain_arena?.routing||{};rows.push(["Brain Arena",arena.ready?`${arena.measured_count}/${arena.candidate_count} main models measured`:(arena.candidate_count?"Collecting objective model scores":"No configured main models"),arena.ready?"good":arena.candidate_count?"warn":"warn"]);const qlab=d.r23_quality_lab||{},qsignal=qlab.signal||{};rows.push(["Progressive Quality Lab",qsignal.ready?`${String(qsignal.tier||"").toUpperCase()} · ${qsignal.case_count||0} cases · ${qsignal.measured_count||0}/${qsignal.candidate_count||0} models`:`Manual · ${qlab.tiers?.screen||12}/${qlab.tiers?.standard||24}/${qlab.tiers?.deep||36} cases`,qsignal.ready?"good":"warn"]);rows.push(["Cloud brain",d.r15_cloud?.durable?"Durable PostgreSQL sync active":(d.r15_cloud?.configured?"Configured · check connection":"Optional · DATABASE_URL not set"),d.r15_cloud?.durable?"good":"warn"]);rows.push(["Code workspace",d.r16_workspace?.python?"Python runtime available":"Python runtime unavailable",d.r16_workspace?.python?"good":"bad"]);rows.push(["Computer agent",d.r17_computer?.verified?"Remote computer verified":"Not connected",d.r17_computer?.verified?"good":"warn"]);rows.push(["Long jobs",Object.entries(d.r17_jobs||{}).map(([k,v])=>`${k} ${v}`).join(" · ")||"Ready","good"]);rows.push(["Monitoring",`${d.r18_monitor?.active_watches||0} watches · ${d.r18_monitor?.unseen_alerts||0} alerts`,"good"]);rows.push(["Self-created tools",`${d.r19_safe_tools?.safe_tools||0} saved`,"good"]);rows.push(["Training dataset",`${d.r19_training?.examples||0} approved examples`,d.r19_training_runtime?.training_available?"good":"warn"]);rows.push(["Knowledge base",`${d.knowledge_base?.items??0} items · ${d.knowledge_base?.projects??0} projects`,"good"]);rows.push(["Task queue",`${d.task_queue?.queued??0} queued · ${d.task_queue?.running??0} running`,"good"]);for(const w of d.warnings||[])rows.push(["Warning",w,"warn"]);$("diagnosticDetails").innerHTML=rows.map(r=>`<div class="diagRow"><span>${escapeHTML(r[0])}</span><b>${escapeHTML(String(r[1]))}</b><i class="diagState ${r[2]}">${r[2]==="good"?"PASS":r[2]==="warn"?"CHECK":"FAIL"}</i></div>`).join("")||'<div class="diagRow"><span>Status</span><b>No issues reported.</b><i class="diagState good">PASS</i></div>'}catch(e){s.className="diagnosticSummary bad";s.innerHTML=`<span>Diagnostics could not reach the RONN server: ${escapeHTML(e.message)}</span>`}}
async function testProvider(provider){showToast(`Testing ${provider} connection and chat completion…`);try{const r=await fetch(`${CORE_API}/providers/check?provider=${encodeURIComponent(provider)}`,{headers:apiHeaders()});const d=await r.json();showToast(d.verified?`${provider.toUpperCase()} chat verified with ${d.sample_model||"a live model"}.`:`${provider.toUpperCase()} test failed: ${d.message||"completion not verified"}`);runDiagnostics()}catch(e){showToast("Provider test failed: "+e.message)}}

let brainArenaCheckStarted=false;
function arenaSnapshot(){
  const raw=loadJSON(ARENA_KEY,{version:"R23-ARENA-SNAPSHOT-1",rows:[]});
  const rows=Array.isArray(raw?.rows)?raw.rows:[];
  return {
    version:"R23-ARENA-SNAPSHOT-1",
    rows:rows.slice(0,100).map(x=>({
      model:String(x.model||"").slice(0,220),
      domain:String(x.domain||"").slice(0,40),
      score:Number(x.score||0),
      latency:Number(x.latency||0),
      samples:Number(x.samples||0)|0,
      updated:Number(x.updated||0)
    })).filter(x=>x.model&&["main","instruction","reasoning","coding","certification","shadow_instruction","shadow_reasoning","shadow_coding","quality_screen","quality_standard","quality_deep"].includes(x.domain))
  }
}
function saveArenaSnapshot(snapshot){
  if(!snapshot||snapshot.version!=="R23-ARENA-SNAPSHOT-1"||!Array.isArray(snapshot.rows))return;
  const existing=arenaSnapshot().rows;
  const merged=new Map();
  const cutoff=(Date.now()/1000)-45*24*3600;
  for(const row of [...existing,...snapshot.rows]){
    const model=String(row?.model||"").slice(0,220),domain=String(row?.domain||"").slice(0,40);
    const updated=Number(row?.updated||0);
    if(!model||!["main","instruction","reasoning","coding","certification","shadow_instruction","shadow_reasoning","shadow_coding","quality_screen","quality_standard","quality_deep"].includes(domain)||updated<cutoff)continue;
    const clean={
      model,domain,
      score:Math.max(0,Math.min(100,Number(row?.score||0))),
      latency:Math.max(0,Math.min(120,Number(row?.latency||0))),
      samples:Math.max(0,Math.min(100,Number(row?.samples||0)|0)),
      updated
    };
    const key=model+"|"+domain,prior=merged.get(key);
    if(!prior||clean.updated>=Number(prior.updated||0))merged.set(key,clean);
  }
  const rows=[...merged.values()].sort((a,b)=>Number(b.updated||0)-Number(a.updated||0)).slice(0,100);
  saveJSON(ARENA_KEY,{version:"R23-ARENA-SNAPSHOT-1",rows});
}
async function maybeRunBrainArena(){
  if(brainArenaCheckStarted)return;
  brainArenaCheckStarted=true;
  try{
    const local=arenaSnapshot();
    if(local.rows.length){
      const restore=await fetch("/api/r23/brain-arena/restore",{
        method:"POST",
        headers:apiHeaders({"Content-Type":"application/json"}),
        body:JSON.stringify({snapshot:local})
      });
      if(!restore.ok){brainArenaCheckStarted=false;return}
    }

    const sr=await fetch("/api/r23/brain-arena",{headers:apiHeaders(),cache:"no-store"});
    if(!sr.ok){brainArenaCheckStarted=false;return}
    const s=await sr.json();
    const routing=s.routing||{},cert=s.certification||{};
    if(!routing.candidate_count){brainArenaCheckStarted=false;return}

    const baseFresh=!!routing.ready&&Number(routing.oldest||0)>0&&((Date.now()/1000)-Number(routing.oldest||0)<6*24*3600);
    const certFresh=!Number(cert.required_models?.length||0)||cert.ready===true;
    const fresh=baseFresh&&certFresh;
    if(fresh){
      try{
        const er=await fetch("/api/r23/brain-arena/export",{headers:apiHeaders(),cache:"no-store"});
        if(er.ok){const ed=await er.json();saveArenaSnapshot(ed.snapshot)}
      }catch{}
      return;
    }

    const rr=await fetch("/api/r23/brain-arena/run",{method:"POST",headers:apiHeaders()});
    if(!rr.ok){brainArenaCheckStarted=false;return}
    const d=await rr.json();
    saveArenaSnapshot(d.snapshot);
  }catch{brainArenaCheckStarted=false}
}

async function runQualityLab(tier="screen"){
  tier=String(tier||"screen").toLowerCase();
  const counts={screen:12,standard:24,deep:36};
  if(!counts[tier])return;
  const btn=$("quality"+tier[0].toUpperCase()+tier.slice(1)+"Btn");
  if(btn)btn.disabled=true;
  showToast(`Running ${tier} Quality Lab · ${counts[tier]} cases per main model…`);
  try{
    const r=await fetch(`/api/r23/quality-lab/run?tier=${encodeURIComponent(tier)}&scope=main`,{method:"POST",headers:apiHeaders()});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||d.reason||"Quality Lab failed.");
    saveArenaSnapshot(d.snapshot);
    const s=d.signal||d.best_shared_signal||{};
    if(d.skipped==="fresh")showToast(`${tier} Quality Lab is already fresh.`);
    else if(s.ready)showToast(`Quality Lab ${tier}: ${s.measured_count||0}/${s.candidate_count||0} models measured.`);
    else showToast("Quality Lab finished, but complete shared evidence is not available yet.");
    runDiagnostics();
  }catch(e){showToast("Quality Lab failed: "+(e.message||e))}
  finally{if(btn)btn.disabled=false}
}

async function showRepairPlan(){try{const d=await (await fetch(CORE_API+"/repair-plan",{headers:apiHeaders()})).json();const first=(d.actions||[])[0];showToast(first?.detail||"No repair action required.");runDiagnostics()}catch(e){showToast("Self-repair analysis failed: "+e.message)}}


const SIDEBAR_KEY="ronnSidebarCompactR11";
if(safeGet(SIDEBAR_KEY)==="1")document.body.classList.add("sidebarCompact");
$("sidebarCollapse").onclick=()=>{document.body.classList.toggle("sidebarCompact");safeSet(SIDEBAR_KEY,document.body.classList.contains("sidebarCompact")?"1":"0");$("sidebarCollapse").textContent=document.body.classList.contains("sidebarCompact")?"›":"‹"};

$("newProjectBtn").onclick=()=>{editingProjectId=null;$("projectName").value="";$("projectContext").value="";$("projectEditor").classList.remove("hidden");$("projectGrid").classList.add("dim");$("projectName").focus()};$("cancelProjectBtn").onclick=closeProjectEditor;
$("saveProjectBtn").onclick=async()=>{const name=$("projectName").value.trim(),context=$("projectContext").value.trim();if(!name)return showToast("Give the project a name.");let id=editingProjectId,p;if(id){p=projects.find(x=>x.id===id);p.name=name;p.context=context;if(p.coreProjectId){try{await fetch(CORE_API+`/projects/${encodeURIComponent(p.coreProjectId)}`,{method:"PATCH",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({name,description:context.slice(0,2000)})})}catch{}}else{try{const r=await fetch(CORE_API+"/projects",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({name,description:context.slice(0,2000)})});const d=await r.json();if(r.ok&&d.project?.project_id)p.coreProjectId=d.project.project_id}catch{}}}else{p={id:uid("project"),name,context};try{const r=await fetch(CORE_API+"/projects",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({name,description:context.slice(0,2000)})});const d=await r.json();if(r.ok&&d.project?.project_id)p.coreProjectId=d.project.project_id}catch{}projects.unshift(p);id=p.id}saveJSON(PROJECT_KEY,projects);safeSet(ACTIVE_PROJECT_KEY,id);closeProjectEditor();renderProjects();updateProjectBadge();refreshActiveProjectBrain();showToast("Project saved and activated.")};
$("deleteProjectBtn").onclick=()=>{if(!editingProjectId)return closeProjectEditor();projects=projects.filter(p=>p.id!==editingProjectId);saveJSON(PROJECT_KEY,projects);if(safeGet(ACTIVE_PROJECT_KEY)===editingProjectId)safeRemove(ACTIVE_PROJECT_KEY);closeProjectEditor();renderProjects();updateProjectBadge();showToast("Project deleted.")};

async function registerDesktopDevice(){
  try{await fetch(CORE_API+"/devices/register",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({device_id:deviceId,name:"RONN Desktop",platform:navigator.platform||"desktop",app_version:"R19"})})}catch{}
}
let robloxPairExpiresAt=0;

function robloxBridgeName(bridge){
  return String(bridge?.name||bridge?.bridge_id||"RONN Roblox Bridge");
}

function renderRobloxStudioStatus(data){
  const state=$("robloxStudioState"),list=$("robloxStudioList"),disconnect=$("robloxDisconnectBtn");
  if(!state||!list)return;

  const bridges=Array.isArray(data?.bridges)?data.bridges:[];
  const online=bridges.filter(b=>b?.online&&b?.mcp_connected);
  const selectedBridge=String(data?.selected_bridge_id||"");
  const selectedStudio=String(data?.selected_studio_id||"");

  state.textContent=data?.online?"Connected":bridges.length?"Bridge offline":"Not connected";
  state.classList.toggle("active",!!data?.online);
  disconnect?.classList.toggle("hidden",!bridges.length);

  const rows=[];
  for(const bridge of bridges){
    const bridgeId=String(bridge?.bridge_id||"");
    const isOnline=!!bridge?.online&&!!bridge?.mcp_connected;
    rows.push(`<div class="ownerRow"><div><b>${escapeHTML(robloxBridgeName(bridge))}</b><small>${isOnline?"Studio MCP connected":bridge?.online?"Bridge online · waiting for Studio MCP":"Bridge offline"}${bridge?.last_error?` · ${escapeHTML(String(bridge.last_error).slice(0,110))}`:""}</small></div><i class="diagState ${isOnline?"good":"warn"}">${isOnline?"READY":"WAIT"}</i></div>`);
    if(isOnline){
      const studios=Array.isArray(bridge?.studios)?bridge.studios:[];
      for(const studio of studios){
        const sid=String(studio?.studio_id||studio?.id||"");
        if(!sid)continue;
        const chosen=bridgeId===selectedBridge&&sid===selectedStudio;
        rows.push(`<div class="ownerRow"><div><b>${escapeHTML(String(studio?.name||"Roblox Studio"))}</b><small>${studio?.place_id?"Place "+escapeHTML(String(studio.place_id)):"Connected Studio"} · ${chosen?"Selected":"Available"}</small></div><button class="${chosen?"primarySmall":"ghost"}" data-roblox-bridge="${escapeHTML(bridgeId)}" data-roblox-studio="${escapeHTML(sid)}" ${chosen?"disabled":""}>${chosen?"Selected":"Use this Studio"}</button></div>`);
      }
      if(!studios.length)rows.push('<div class="ownerRow"><div><b>Waiting for a Studio window</b><small>Open Roblox Studio and enable Assistant → Manage MCP Servers → Enable Studio as MCP server.</small></div></div>');
    }
  }
  list.innerHTML=rows.length?rows.join(""):'<div class="emptyState">Download the bridge, enable Studio MCP, then connect this PC.</div>';

  if(data?.online){
    $("robloxPairBox")?.classList.add("hidden");
    robloxPairExpiresAt=0;
  }
}

async function refreshRobloxStudio(){
  if(!$("robloxStudioState"))return;
  try{
    const r=await fetch("/api/roblox/status",{headers:apiHeaders(),cache:"no-store"});
    if(!r.ok)throw new Error("status unavailable");
    renderRobloxStudioStatus(await r.json());
  }catch{
    const state=$("robloxStudioState");
    if(state){state.textContent="Unavailable";state.classList.remove("active")}
  }
}

async function startRobloxPairing(){
  const btn=$("robloxPairBtn"),box=$("robloxPairBox"),code=$("robloxPairCode"),expiry=$("robloxPairExpiry");
  if(btn){btn.disabled=true;btn.textContent="Creating code…"}
  try{
    const r=await fetch("/api/roblox/pair/start",{method:"POST",headers:apiHeaders()});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||"Could not create a pairing code.");
    robloxPairExpiresAt=Number(d.expires_at||0)*1000;
    if(code)code.textContent=String(d.pair_code||"");
    if(expiry)expiry.textContent="Use this once in PAIR_AND_RUN_WINDOWS.bat. It expires in about 10 minutes.";
    box?.classList.remove("hidden");
    try{await navigator.clipboard.writeText(String(d.pair_code||""))}catch{}
    showToast("Pairing code created and copied.");
  }catch(e){
    showToast(e.message||"Could not create pairing code.");
  }finally{
    if(btn){btn.disabled=false;btn.textContent="Connect Roblox Studio"}
  }
}

async function downloadRobloxBridge(){
  const btn=$("robloxBridgeDownloadBtn");
  if(btn){btn.disabled=true;btn.textContent="Preparing bridge…"}
  try{
    const r=await fetch("/api/roblox/bridge/windows.zip",{headers:apiHeaders(),cache:"no-store"});
    if(!r.ok){
      const d=await r.json().catch(()=>({}));
      throw new Error(d.detail||"Bridge download failed.");
    }
    const blob=await r.blob();
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download="RONN_Roblox_Bridge_Windows.zip";
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1500);
    showToast("RONN Roblox Bridge downloaded.");
  }catch(e){
    showToast(e.message||"Bridge download failed.");
  }finally{
    if(btn){btn.disabled=false;btn.textContent="Download Windows bridge"}
  }
}

async function selectRobloxStudio(bridgeId,studioId){
  if(!bridgeId||!studioId)return;
  try{
    const r=await fetch("/api/roblox/select",{
      method:"POST",
      headers:apiHeaders({"Content-Type":"application/json"}),
      body:JSON.stringify({bridge_id:bridgeId,studio_id:studioId})
    });
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||"Could not select that Studio window.");
    showToast("RONN will use this Roblox Studio window.");
    refreshRobloxStudio();
  }catch(e){showToast(e.message||"Studio selection failed.")}
}

async function disconnectRobloxBridge(){
  try{
    const status=await (await fetch("/api/roblox/status",{headers:apiHeaders(),cache:"no-store"})).json();
    const id=String(status?.selected_bridge_id||(status?.bridges||[])[0]?.bridge_id||"");
    if(!id)return showToast("No bridge is paired.");
    const r=await fetch("/api/roblox/revoke",{
      method:"POST",
      headers:apiHeaders({"Content-Type":"application/json"}),
      body:JSON.stringify({bridge_id:id})
    });
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||"Disconnect failed.");
    showToast("RONN Roblox Bridge disconnected.");
    refreshRobloxStudio();
  }catch(e){showToast(e.message||"Disconnect failed.")}
}

async function refreshR19Capabilities(){
  const box=$("r19CapabilityMatrix");if(!box)return;
  try{
    const r=await fetch("/api/r19/capabilities",{headers:apiHeaders(),cache:"no-store"});
    const d=await r.json();if(!r.ok)throw new Error(d.detail||"Capability check failed.");
    const rows=[];
    const label=s=>String(s||"").replaceAll("_"," ").replace(/\b\w/g,m=>m.toUpperCase());
    for(const [k,v] of Object.entries(d.working_now||{}))rows.push({name:label(k),state:!!v?"on":"wait",note:!!v?"Active now":"Unavailable"});
    const cloud=d.connected_when_configured?.permanent_cloud_brain||{};
    rows.push({name:"Permanent Cloud Brain",state:cloud.durable?"on":"wait",note:cloud.durable?"Durable sync active":cloud.configured?"Configured · connection not verified":"Needs DATABASE_URL"});
    const computer=d.connected_when_configured?.computer_control||{};
    rows.push({name:"Computer Control",state:computer.verified?"on":"wait",note:computer.verified?"Remote computer verified":"Needs isolated computer runtime"});
    const training=d.connected_when_configured?.custom_model_training||{};
    rows.push({name:"RONN Custom Model Training",state:training.training_available?"on":"wait",note:training.training_available?"Training runtime connected":"Dataset builder active · trainer not connected"});
    const controller=d.central_controller||{};
    rows.unshift({name:"R20 Central Controller",state:controller.central_controller?"on":"wait",note:controller.agent_refinement_enabled?"Agents SDK active · one-controller routing":"One-controller routing · deterministic fallback"});
    rows.push({name:"Live Voice",state:("SpeechRecognition" in window||"webkitSpeechRecognition" in window)?"on":"wait",note:"Browser-dependent"});
    rows.push({name:"Screen Context",state:navigator.mediaDevices?.getDisplayMedia?"on":"wait",note:"Browser screen-share"});
    box.innerHTML=rows.map(x=>`<div class="r19CapRow ${x.state}"><i></i><div><b>${escapeHTML(x.name)}</b><small>${escapeHTML(x.note)}</small></div></div>`).join("");
  }catch(e){box.innerHTML=`<div class="emptyState">R19 status unavailable: ${escapeHTML(e.message)}</div>`}
}

async function refreshEcosystemStatus(){
  const chips=$("ecosystemChips");if(!chips)return;
  try{const r=await fetch(CORE_API+"/ecosystem/status",{headers:apiHeaders()});const d=await r.json();const c=d.credits||{};chips.innerHTML=`<span>Core sync ${Number(d.sync_cursor||0)}</span><span>${Number(d.devices||0)} device${Number(d.devices||0)===1?"":"s"}</span><span>${Number(d.plugins||0)} plugins</span><span>${Number(d.unread_notifications||0)} notifications</span><span>${c.unlimited?"Owner unlimited":`Credits ${c.balance??"—"}`}</span>`}catch{chips.innerHTML="<span>Ecosystem unavailable</span>"}
}
async function refreshOwnerAccess(){
  if(!$("opStatus"))return;
  try{
    const r=await fetch(CORE_API+"/owner/status",{headers:apiHeaders()});
    const d=await r.json();
    const active=!!d.op_active;
    $("opStatus").textContent=active?"Active":"";
    $("opStatus").classList.toggle("active",active);
    $("ownerAccessCard")?.classList.toggle("hidden",!active);
    $("ownerPanel")?.classList.toggle("hidden",!active);
    if(active){
      $("opPlan").textContent="Owner Unlimited";
      $("opCredits").textContent="Unlimited";
      await Promise.all([refreshOwnerDevices(),refreshFeatureFlags(),refreshVault(),refreshOwnerStats()]);
    }
  }catch{}
}
async function refreshOwnerStats(){try{const d=await (await fetch(CORE_API+"/ecosystem/status",{headers:apiHeaders()})).json();$("ownerDeviceCount").textContent=String(d.devices||0);$("ownerSyncCursor").textContent=String(d.sync_cursor||0)}catch{}}
async function refreshOwnerDevices(){const box=$("ownerDeviceList");if(!box)return;try{const d=await (await fetch(CORE_API+"/devices",{headers:apiHeaders()})).json();box.innerHTML="";(d.devices||[]).forEach(dev=>{const row=document.createElement("div");row.className="ownerRow";row.innerHTML=`<div><b>${escapeHTML(dev.name||"RONN device")}</b><small>${escapeHTML(dev.platform||"unknown")} · ${dev.trusted?"trusted":"standard"}${dev.revoked?" · revoked":""}</small></div>${dev.device_id!==deviceId&&!dev.revoked?`<button class="dangerText" data-revoke-device="${escapeHTML(dev.device_id)}">Revoke</button>`:""}`;box.appendChild(row)});if(!box.children.length)box.innerHTML='<div class="emptyState">No registered devices yet.</div>'}catch{}}
async function generateRecoveryCodes(){try{const r=await fetch(CORE_API+"/owner/recovery-codes",{method:"POST",headers:apiHeaders()});const d=await r.json();if(!r.ok)return showToast(d.detail||"Could not create recovery codes.");const box=$("opRecoveryBox");box.classList.remove("hidden");box.innerHTML=`<b>One-time recovery codes</b><p>Save these somewhere private. Each code works once.</p><pre>${escapeHTML((d.codes||[]).join("\n"))}</pre>`}catch{}}
async function createOwnerBackup(){try{const r=await fetch(CORE_API+"/backups",{method:"POST",headers:apiHeaders()});const d=await r.json();if(!r.ok)return showToast(d.detail||"Backup failed.");showToast(`Backup created · ${(d.backup?.files||[]).length} databases`)}catch{showToast("Backup failed.")}}
async function refreshFeatureFlags(){const box=$("featureFlagList");if(!box)return;try{const d=await (await fetch(CORE_API+"/feature-flags",{headers:apiHeaders()})).json();box.innerHTML="";Object.entries(d.flags||{}).sort().forEach(([flag,enabled])=>{const row=document.createElement("label");row.className="flagRow";row.innerHTML=`<span>${escapeHTML(flag.replaceAll("_"," "))}</span><input type="checkbox" data-flag="${escapeHTML(flag)}" ${enabled?"checked":""}>`;box.appendChild(row)})}catch{}}
async function refreshVault(){const box=$("vaultList");if(!box)return;try{const d=await (await fetch(CORE_API+"/vault",{headers:apiHeaders()})).json();box.innerHTML="";(d.items||[]).forEach(item=>{const row=document.createElement("div");row.className="ownerRow";row.innerHTML=`<div><b>${escapeHTML(item.title||"Secure note")}</b><small>Encrypted at rest</small></div><button class="dangerText" data-vault-delete="${escapeHTML(item.id)}">Delete</button>`;box.appendChild(row)});if(!box.children.length)box.innerHTML='<div class="emptyState">Vault is empty.</div>'}catch{}}
async function saveVaultItem(){const title=$("vaultTitle")?.value.trim()||"Secure note",text=$("vaultText")?.value||"";if(!text.trim())return showToast("Enter something to secure.");const r=await fetch(CORE_API+"/vault",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({title,text})});if(r.ok){$("vaultTitle").value="";$("vaultText").value="";showToast("Saved encrypted note.");refreshVault()}else{const d=await r.json().catch(()=>({}));showToast(d.detail||"Vault save failed.")}}

$("memoryAddBtn").onclick=async()=>{const text=$("memoryInput").value.trim();if(!text)return;const r=await fetch(CORE_API+"/memory",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({text})});const d=await r.json().catch(()=>({}));if(!r.ok)return showToast(d.detail||"Could not save memory");$("memoryInput").value="";refreshMemory();refreshStatus()};$("memoryInput").addEventListener("keydown",e=>{if(e.key==="Enter")$("memoryAddBtn").click()});
$("newChat").onclick=()=>{currentChatId="";safeRemove(CURRENT_KEY);currentChat();renderMessages();renderChatList();showView("chat");if(window.innerWidth>780)input.focus()};
$("clearBtn").onclick=()=>$("confirmModal").classList.remove("hidden");$("cancelClearBtn").onclick=()=>$("confirmModal").classList.add("hidden");$("confirmClearBtn").onclick=()=>{const c=currentChat();c.messages=[];c.title="New chat";c.updated=Date.now();saveChats();renderMessages();$("confirmModal").classList.add("hidden");showToast("Conversation cleared.")};
$("exportBtn").onclick=()=>{const c=currentChat(),md=`# ${c.title}\n\n`+c.messages.map(m=>`## ${m.role==="user"?"You":"RONN"}\n\n${m.content}\n`).join("\n");const blob=new Blob([md],{type:"text/markdown"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=(c.title.replace(/[^a-z0-9_-]+/gi,"_")||"ronn-chat")+".md";a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$("chatSearch").addEventListener("input",renderChatList);qsa(".navBtn").forEach(b=>b.onclick=()=>showView(b.dataset.view));qsa("[data-view-target]").forEach(b=>b.onclick=()=>showView(b.dataset.viewTarget));const plusMenu=$("plusMenu");$("attachBtn").onclick=e=>{e.stopPropagation();plusMenu?.classList.toggle("hidden")};$("plusAttach").onclick=()=>{plusMenu?.classList.add("hidden");fileInput.click()};$("plusNewChat").onclick=()=>{plusMenu?.classList.add("hidden");$("newChat").click()};$("plusProject").onclick=()=>showView("projects");$("plusMemory").onclick=()=>showView("memory");fileInput.onchange=e=>{addFiles(e.target.files);fileInput.value=""};sendBtn.onclick=()=>sendMessage(false);stopBtn.onclick=async()=>{const id=currentRequestId;controller?.abort();if(id){try{await fetch(`/api/tasks/${encodeURIComponent(id)}/cancel`,{method:"POST",headers:apiHeaders()})}catch{}}};input.addEventListener("input",autoSize);input.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMessage(false)}});$("presetRow").addEventListener("click",e=>{const b=e.target.closest("[data-prompt]");if(b){input.value=b.dataset.prompt;autoSize();input.focus()}});$("runDiagnosticsBtn").onclick=runDiagnostics;$("testGroqBtn").onclick=()=>testProvider("groq");$("testNvidiaBtn").onclick=()=>testProvider("nvidia");if($("testOpenRouterBtn"))$("testOpenRouterBtn").onclick=()=>testProvider("openrouter");$("repairPlanBtn").onclick=showRepairPlan;$("queueAddBtn").onclick=addQueueItem;$("kbSearchBtn").onclick=searchKnowledge;$("queueInput").addEventListener("keydown",e=>{if(e.key==="Enter")addQueueItem()});$("kbSearchInput").addEventListener("keydown",e=>{if(e.key==="Enter")searchKnowledge()});$("queueList").addEventListener("click",async e=>{const id=e.target.dataset.queueDone;if(id){await fetch(CORE_API+`/tasks/${encodeURIComponent(id)}`,{method:"PATCH",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({status:"complete"})});refreshAgentOps()}});
messages.addEventListener("click",e=>{if(e.target.classList.contains("rateMsg")){const wrap=e.target.closest(".message"),request_id=wrap?.dataset.requestId||"",rating=Number(e.target.dataset.rating||0);if(request_id&&(rating===1||rating===-1)){recordOutcome(wrap?.dataset.model||"",wrap?.dataset.profile||"",rating);fetch("/api/feedback",{method:"POST",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({request_id,rating,note:""})}).then(r=>r.json()).then(()=>showToast(rating===1?"Feedback saved.":"Feedback saved — RONN will treat this route as weaker for similar work."));wrap.querySelectorAll(".rateMsg").forEach(b=>b.disabled=true)}return}const copy=e.target.closest(".copyCode");if(copy){navigator.clipboard.writeText(copy.closest(".codeWrap").querySelector("code").innerText);copy.textContent="Copied";setTimeout(()=>copy.textContent="Copy",1000);return}const cm=e.target.closest(".copyMsg");if(cm){navigator.clipboard.writeText(cm.closest(".aiBubble").querySelector(".answer").innerText);cm.textContent="Copied";setTimeout(()=>cm.textContent="Copy",1000);return}const why=e.target.closest(".whyMsg");if(why){const text=e.target.closest(".message")?.dataset.decision||"RONN selected the route based on task type, freshness, risk, and verification needs.";showToast(text);return}const retry=e.target.closest(".retryMsg");if(retry){sendMessage(true);return}const verify=e.target.closest(".verifyMsg");if(verify){const c=currentChat(),lastUser=[...c.messages].reverse().find(m=>m.role==="user")?.content||"";input.value=`Verify your previous answer to this request: ${lastUser}\n\nCheck factual claims, assumptions, missing requirements, and anything you claimed was tested or completed. Correct the answer if needed.`;$("reviewToggle").checked=true;autoSize();input.focus();return}const p=e.target.closest("[data-prompt]");if(p){input.value=p.dataset.prompt;autoSize();input.focus()}});
document.addEventListener("click",e=>{if(plusMenu&&!e.target.closest(".composerWrap"))plusMenu.classList.add("hidden");const b=e.target.closest(".downloadCode");if(!b)return;const wrap=b.closest(".codeWrap"),code=wrap?.querySelector("pre code")?.innerText||"",lang=(wrap?.querySelector(".codeHead span")?.textContent||"code").toLowerCase(),ext=({lua:"lua",luau:"luau",python:"py",py:"py",javascript:"js",js:"js",typescript:"ts",ts:"ts",html:"html",css:"css",json:"json",markdown:"md",md:"md"})[lang]||"txt",blob=new Blob([code],{type:"text/plain"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`ronn_code.${ext}`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)});
messages.addEventListener("scroll",()=>{updateJumpLatest();if(busy)streamFollowLatest=nearBottom()},{passive:true});
if(jumpLatest)jumpLatest.onclick=()=>scrollToLatest(true);
window.addEventListener("resize",()=>updateJumpLatest(),{passive:true});
document.addEventListener("paste",e=>{const files=[...e.clipboardData.files];if(files.length){e.preventDefault();addFiles(files)}});let drag=0;document.addEventListener("dragenter",e=>{e.preventDefault();drag++;$("dropOverlay").classList.add("show")});document.addEventListener("dragleave",e=>{e.preventDefault();drag--;if(drag<=0){drag=0;$("dropOverlay").classList.remove("show")}});document.addEventListener("dragover",e=>e.preventDefault());document.addEventListener("drop",e=>{e.preventDefault();drag=0;$("dropOverlay").classList.remove("show");addFiles(e.dataTransfer.files)});
document.addEventListener("keydown",e=>{if(e.ctrlKey&&e.key.toLowerCase()==="n"){e.preventDefault();$("newChat").click()}if(e.key==="Escape"){$("confirmModal").classList.add("hidden");if(controller)controller.abort()}});

// R19 live voice: browser-side speech recognition + speech synthesis. Audio is not uploaded or stored.
const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
let recognizer=null;
function speakRONN(text){
  if(!voiceMode||!("speechSynthesis" in window)||!String(text||"").trim())return;
  try{
    if(recognizer)recognizer.stop();
    window.speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(String(text).replace(/[`*_#>]/g," ").slice(0,5000));
    u.rate=1.02;u.pitch=.96;u.lang=navigator.language||"en-US";voiceSpeaking=true;
    u.onend=()=>{voiceSpeaking=false;if(voiceMode)try{recognizer?.start()}catch{}};
    u.onerror=()=>{voiceSpeaking=false;if(voiceMode)try{recognizer?.start()}catch{}};
    window.speechSynthesis.speak(u);
  }catch{}
}
function stopVoiceMode(){
  voiceMode=false;voiceSpeaking=false;
  try{recognizer?.stop()}catch{}
  try{window.speechSynthesis?.cancel()}catch{}
  const b=$("voiceBtn");if(b){b.classList.remove("listening");b.textContent="◉"}
}
if($("voiceBtn")){
  if(SpeechRecognition){
    recognizer=new SpeechRecognition();recognizer.lang=navigator.language||"en-US";recognizer.interimResults=false;recognizer.continuous=true;
    recognizer.onstart=()=>{if(voiceMode){$("voiceBtn").classList.add("listening");$("voiceBtn").textContent="●"}};
    recognizer.onend=()=>{if(voiceMode&&!voiceSpeaking)setTimeout(()=>{try{recognizer.start()}catch{}},250);else if(!voiceMode){$("voiceBtn").classList.remove("listening");$("voiceBtn").textContent="◉"}};
    recognizer.onresult=e=>{let final="";for(let i=e.resultIndex;i<e.results.length;i++){if(e.results[i].isFinal)final+=(e.results[i][0]?.transcript||"")+" "}final=final.trim();if(final&&!busy){input.value=final;autoSize();sendMessage(false)}};
    recognizer.onerror=e=>{if(!["no-speech","aborted"].includes(e.error||""))showToast(`Voice: ${e.error||"not available"}`)};
    $("voiceBtn").onclick=()=>{if(voiceMode){stopVoiceMode();showToast("Live voice off.")}else{voiceMode=true;$("voiceBtn").textContent="●";try{recognizer.start()}catch{}showToast("Live voice on.")}};
  }else{$("voiceBtn").disabled=true;$("voiceBtn").title="Live voice is not supported by this browser"}
}
if($("screenBtn"))$("screenBtn").onclick=toggleScreenContext;


if($("webAuthUnlock"))$("webAuthUnlock").onclick=unlockWebAuth;
if($("webAuthSecret"))$("webAuthSecret").addEventListener("keydown",e=>{if(e.key==="Enter")unlockWebAuth()});
if("serviceWorker" in navigator){window.addEventListener("load",()=>navigator.serviceWorker.register("/service-worker.js?v=RONN-R23-ROBLOX-MCP1",{updateViaCache:"none"}).catch(()=>{}))}

if($("robloxPairBtn"))$("robloxPairBtn").onclick=startRobloxPairing;
if($("robloxBridgeDownloadBtn"))$("robloxBridgeDownloadBtn").onclick=downloadRobloxBridge;
if($("robloxRefreshBtn"))$("robloxRefreshBtn").onclick=refreshRobloxStudio;
if($("robloxDisconnectBtn"))$("robloxDisconnectBtn").onclick=disconnectRobloxBridge;
if($("robloxCopyPairBtn"))$("robloxCopyPairBtn").onclick=async()=>{const code=$("robloxPairCode")?.textContent||"";if(!code||code==="—")return;try{await navigator.clipboard.writeText(code);showToast("Pairing code copied.")}catch{showToast("Could not copy the code.")}};
if($("robloxStudioList"))$("robloxStudioList").addEventListener("click",e=>{const b=e.target.closest("[data-roblox-studio]");if(b&&!b.disabled)selectRobloxStudio(b.dataset.robloxBridge,b.dataset.robloxStudio)});
if($("ownerRefreshBtn"))$("ownerRefreshBtn").onclick=()=>{refreshOwnerAccess();refreshEcosystemStatus()};
if($("refreshR19Btn"))$("refreshR19Btn").onclick=refreshR19Capabilities;
if($("qualityScreenBtn"))$("qualityScreenBtn").onclick=()=>runQualityLab("screen");
if($("qualityStandardBtn"))$("qualityStandardBtn").onclick=()=>runQualityLab("standard");
if($("qualityDeepBtn"))$("qualityDeepBtn").onclick=()=>runQualityLab("deep");
if($("ownerRecoveryBtn"))$("ownerRecoveryBtn").onclick=generateRecoveryCodes;
if($("ownerBackupBtn"))$("ownerBackupBtn").onclick=createOwnerBackup;
if($("vaultSaveBtn"))$("vaultSaveBtn").onclick=saveVaultItem;
if($("ownerDeviceList"))$("ownerDeviceList").addEventListener("click",async e=>{const id=e.target.dataset.revokeDevice;if(!id)return;const r=await fetch(CORE_API+`/devices/${encodeURIComponent(id)}`,{method:"DELETE",headers:apiHeaders()});if(r.ok){showToast("Device revoked.");refreshOwnerDevices();refreshOwnerStats()}});
if($("vaultList"))$("vaultList").addEventListener("click",async e=>{const id=e.target.dataset.vaultDelete;if(!id)return;const r=await fetch(CORE_API+`/vault/${encodeURIComponent(id)}`,{method:"DELETE",headers:apiHeaders()});if(r.ok){showToast("Vault item deleted.");refreshVault()}});
if($("featureFlagList"))$("featureFlagList").addEventListener("change",async e=>{const flag=e.target.dataset.flag;if(!flag)return;const r=await fetch(CORE_API+`/feature-flags/${encodeURIComponent(flag)}`,{method:"PATCH",headers:apiHeaders({"Content-Type":"application/json"}),body:JSON.stringify({enabled:!!e.target.checked})});if(!r.ok){e.target.checked=!e.target.checked;showToast("Feature flag change failed.")}else showToast("Feature flag updated.")});
registerDesktopDevice();refreshEcosystemStatus();refreshRobloxStudio();
ensureWebAuth();

if(!chats.length)currentChat();else if(!chats.some(c=>c.id===currentChatId)){currentChatId=chats[0].id;safeSet(CURRENT_KEY,currentChatId)}
renderChatList();renderMessages();bindPromptButtons();updateProjectBadge();refreshStatus();refreshMemory();setInterval(refreshStatus,12000);setInterval(refreshRobloxStudio,12000);setTimeout(maybeRunBrainArena,8000);if(window.innerWidth>780)input.focus();

window.__RONN_UI_READY=true;

let mobileViewportFrame=0;
const isiOSWebKit=/iP(hone|ad|od)/i.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
let mobileViewportBaseHeight=Math.max(1,Math.round(window.innerHeight||document.documentElement.clientHeight||1));
let mobileKeyboardState=false;

function syncMobileViewport(){
  cancelAnimationFrame(mobileViewportFrame);
  mobileViewportFrame=requestAnimationFrame(()=>{
    const root=document.documentElement;
    if(window.innerWidth>780){
      root.style.removeProperty("--ronn-vv-height");
      document.body.classList.remove("mobileKeyboardOpen","mobileInputFocused");
      mobileKeyboardState=false;
      return;
    }

    const inputFocused=document.activeElement===input;

    // iOS Safari already pans its visual viewport to the focused textarea.
    // Resizing RONN during that keyboard animation creates the blank-screen
    // bounce shown in the screen recording, so do not fight Safari here.
    if(isiOSWebKit){
      root.style.removeProperty("--ronn-vv-height");
      document.body.classList.toggle("mobileKeyboardOpen",inputFocused);
      mobileKeyboardState=inputFocused;
      return;
    }

    const vv=window.visualViewport;
    const layoutH=Math.max(1,Math.round(window.innerHeight||document.documentElement.clientHeight||1));
    const visibleH=Math.max(1,Math.round(vv&&vv.height>0?vv.height:layoutH));
    if(!inputFocused)mobileViewportBaseHeight=Math.max(visibleH,layoutH);
    const keyboard=inputFocused&&Math.max(0,mobileViewportBaseHeight-visibleH)>110;
    root.style.setProperty("--ronn-vv-height",visibleH+"px");
    document.body.classList.toggle("mobileKeyboardOpen",keyboard);
    mobileKeyboardState=keyboard;
  });
}

syncMobileViewport();
window.addEventListener("resize",syncMobileViewport,{passive:true});
window.addEventListener("orientationchange",()=>setTimeout(syncMobileViewport,140),{passive:true});
if(window.visualViewport&&!isiOSWebKit){
  window.visualViewport.addEventListener("resize",syncMobileViewport,{passive:true});
}

input.addEventListener("focus",()=>{
  if(window.innerWidth<=780){
    document.body.classList.add("mobileInputFocused","mobileKeyboardOpen");
    if(!isiOSWebKit)syncMobileViewport();
  }
});
input.addEventListener("blur",()=>{
  document.body.classList.remove("mobileInputFocused","mobileKeyboardOpen");
  mobileKeyboardState=false;
  if(!isiOSWebKit)setTimeout(syncMobileViewport,120);
});

function setMobileNav(open){
  document.body.classList.toggle("mobileNavOpen",!!open);
  const btn=$("mobileMenuBtn");
  if(btn)btn.setAttribute("aria-expanded",open?"true":"false");
}
if($("mobileMenuBtn"))$("mobileMenuBtn").onclick=()=>setMobileNav(!document.body.classList.contains("mobileNavOpen"));
if($("mobileNewChatBtn"))$("mobileNewChatBtn").onclick=()=>{$("newChat").click();setMobileNav(false)};
if($("sidebarScrim"))$("sidebarScrim").onclick=()=>setMobileNav(false);
qsa(".navBtn").forEach(b=>b.addEventListener("click",()=>{if(window.innerWidth<=780)setMobileNav(false)}));
window.addEventListener("resize",()=>{if(window.innerWidth>780)setMobileNav(false)},{passive:true});
