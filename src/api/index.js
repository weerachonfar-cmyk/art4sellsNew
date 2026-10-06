/* Chooses which implementation the app talks to, ONCE per page load:
     A4S.api = A4S.remoteApi  (real Python backend)   or   A4S.mockApi  (Phase 2 prototype fallback)
   Rules:  ?mode=mock  forces mock (remembered; local computer only)  |  ?mode=api  clears that  |  otherwise ask GET /api/health:
   backend answers -> "api";  no answer and fallback allowed -> "mock" (banner shown).  ?api=http://host:8000/api points to another backend. */
/* The offline MOCK fallback exists for classroom development on this computer only. On a deployed site a missing backend must be reported
   as unavailable - never replaced by demo data that could be mistaken for the real system. */
var isLocalHost=/^(localhost|127\.0\.0\.1|\[::1\]|)$/.test(location.hostname);
A4S.config={apiBase:"/api",allowMockFallback:isLocalHost,healthTimeoutMs:2500};
(function(){
 AppStorage.remove("token");AppStorage.remove("currentUser");   /* clean-up: older versions kept a login token / user in localStorage. Nothing about the login is stored there any more. */
 var q=new URLSearchParams(location.search),mode=q.get("mode");
 if(mode==="mock")AppStorage.set("forceMock",true);
 if(mode==="api")AppStorage.remove("forceMock");
 if(q.get("api"))AppStorage.set("apiBase",q.get("api"));
 if(q.get("api")==="")AppStorage.remove("apiBase");
 A4S.config.apiBase=AppStorage.get("apiBase","/api");
 A4S.mode="api";A4S.api=A4S.remoteApi;
 var useMock=function(){
  A4S.mode="mock";A4S.api=A4S.mockApi;
  AppState.set("currentUser",null);A4S.devTools=false   /* mock has no authentication: there is never a signed-in user in this mode */
 };
 A4S.ready=(async function(){
  if(AppStorage.get("forceMock",false))useMock();
  else{
   var r=await A4S.http.request("GET","/health",{timeout:A4S.config.healthTimeoutMs});
   if(r.ok)await A4S.api.auth.me();                       /* ask the server whether the session cookie is still valid */
   else if(A4S.config.allowMockFallback)useMock();
   else A4S.backendDown=true;                              /* deployed site, backend/storage unavailable: public pages show an error, private actions are refused */
  }
  try{await A4S.priv.load()}catch(e){A4S.priv.clear()}   /* this user's cart / wishlist / follows / notifications */
 })();
})();
