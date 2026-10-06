/* HTTP client for the Python backend. The ONLY file that calls fetch().
   Every call resolves to {ok:true,status,data} or {ok:false,status,error,errors,code} - it never throws.
   Authentication = an HttpOnly session cookie set by the server: this file never sees, stores or sends a token. */
A4S.http=(function(){
 var TIMEOUT_MS=8000;
 var qs=function(q){
  var p=new URLSearchParams();
  Object.keys(q||{}).forEach(function(k){var v=q[k];if(v!==undefined&&v!==null&&v!==""){p.set(k,v)}});
  var s=p.toString();return s?"?"+s:"";
 };
 var offline=function(){return{ok:false,status:0,error:"Cannot reach the server. Is the backend running?",errors:{},code:"NETWORK"}};
 /* same-origin by default; only an explicitly configured absolute API address (A4S_CORS_ORIGINS on the server) sends the cookie cross-origin */
 var credentialsFor=function(base){return/^https?:\/\//i.test(base||"")?"include":"same-origin"};
 async function request(method,path,opts){
  opts=opts||{};
  var headers={},init={method:method,headers:headers,credentials:credentialsFor(A4S.config.apiBase)},ctl=new AbortController();
  if(opts.body!==undefined){headers["Content-Type"]="application/json";init.body=JSON.stringify(opts.body)}
  init.signal=ctl.signal;
  var timer=setTimeout(function(){ctl.abort()},opts.timeout||TIMEOUT_MS);
  try{
   var res=await fetch(A4S.config.apiBase+path+qs(opts.query),init),data=null;
   try{data=await res.json()}catch(e){data=null}   /* a non-JSON reply is treated as an error below */
   if(res.ok&&data!==null)return{ok:true,status:res.status,data:data};
   var err=(data&&data.error)||{};
   if(res.status===401&&AppState.get("currentUser",null)){AppState.set("currentUser",null);if(A4S.priv)A4S.priv.clear()}   /* session expired: drop the private page state */
   return{ok:false,status:res.status,error:err.message||"Something went wrong",errors:err.fields||{},code:err.code||"ERROR"};
  }catch(e){return offline()}
  finally{clearTimeout(timer)}
 }
 return{
  request:request,
  get:function(path,query){return request("GET",path,{query:query})},
  post:function(path,body){return request("POST",path,{body:body||{}})},
  put:function(path,body){return request("PUT",path,{body:body||{}})},
  del:function(path){return request("DELETE",path)},
  signedIn:function(){return !!AppState.get("currentUser",null)}
 };
})();
