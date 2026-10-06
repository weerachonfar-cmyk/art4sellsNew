/* App state. "currentUser" lives in MEMORY ONLY (never localStorage): the login itself is an HttpOnly cookie that JavaScript cannot read,
   and who is signed in is always re-asked from the server (GET /api/me) on each page load. Other keys still use AppStorage. */
var AppState=(()=>{const subs={},mem={},MEMORY_ONLY={currentUser:true};return{
 get:(k,d)=>MEMORY_ONLY[k]?(Object.prototype.hasOwnProperty.call(mem,k)?mem[k]:d):AppStorage.get(k,d),
 set:(k,v)=>{if(MEMORY_ONLY[k])mem[k]=v;else AppStorage.set(k,v);(subs[k]||[]).concat(subs["*"]||[]).forEach(f=>f(v,k))},
 subscribe:(k,f)=>{(subs[k]=subs[k]||[]).push(f);return()=>{subs[k]=subs[k].filter(x=>x!==f)}}
}})();
