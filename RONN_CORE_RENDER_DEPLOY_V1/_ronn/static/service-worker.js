const CACHE="ronn-assets-r20-mobile2";
const ASSETS=["/static/ronn_home_icon_v2.png","/static/ronn_logo.svg?v=RONN-R19-LOGO2","/static/style.css?v=RONN-R19-CLEAN1","/static/mobile_fit.css?v=RONN-R20-MOBILE2","/static/app.js?v=RONN-R20-MOBILE2","/manifest.webmanifest?v=RONN-R19-MOBILE2"];
self.addEventListener("install",event=>{
  event.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener("activate",event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener("fetch",event=>{
  const req=event.request, url=new URL(req.url);
  if(req.method!=="GET")return;
  if(url.pathname==="/" || url.pathname.endsWith(".js") || url.pathname.endsWith(".css") || url.pathname.startsWith("/api/")){
    event.respondWith(fetch(req,{cache:"no-store"}));
    return;
  }
  event.respondWith(fetch(req).catch(()=>caches.match(req)));
});
