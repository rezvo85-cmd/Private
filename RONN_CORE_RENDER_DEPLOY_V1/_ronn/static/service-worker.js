const CACHE="ronn-assets-v10-1-2";
const ASSETS=["/static/ronn_app_icon.png","/manifest.webmanifest"];
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
  // Never cache the app shell or JavaScript. New deploys must take effect immediately.
  if(url.pathname==="/" || url.pathname.endsWith(".js") || url.pathname.endsWith(".css") || url.pathname.startsWith("/api/")){
    event.respondWith(fetch(req,{cache:"no-store"}));
    return;
  }
  event.respondWith(fetch(req).catch(()=>caches.match(req)));
});
