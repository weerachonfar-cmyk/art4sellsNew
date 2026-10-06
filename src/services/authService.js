/* MOCK auth is DISABLED for login/register (Phase 3.5b).
   The old mock accepted any password for a known email. A secure mock would have to store password hashes in the browser, so
   instead Login/Register need the REAL backend (POST /api/login, password_hash verified on the server). The mock keeps only the read-only data helpers. */
var AuthService=(()=>{
 const S={},NEEDS_BACKEND="Backend unavailable: login and registration need the real backend. MOCK mode has no password authentication, so no one can be signed in.";
 S.NEEDS_BACKEND=NEEDS_BACKEND;
 S.register=()=>Result.fail(NEEDS_BACKEND);
 S.login=()=>Result.fail(NEEDS_BACKEND);
 S.logout=()=>{const u=S.getCurrentUser();if(u)AuditLog.add({actorId:u.id,action:"USER_LOGOUT",targetType:"user",targetId:u.id});AppState.set("currentUser",null)};
 S.getCurrentUser=()=>AppState.get("currentUser",null);
 S.getUser=id=>Data.get("users",id);
 S.getArtists=()=>Data.find("users",u=>u.role==="ARTIST");
 return S;
})();
