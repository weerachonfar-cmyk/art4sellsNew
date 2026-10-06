// Run: node src/test/run.js   (no browser, no packages)
const fs=require("fs"),vm=require("vm"),path=require("path"),mem={};
global.localStorage={getItem:k=>k in mem?mem[k]:null,setItem:(k,v)=>{mem[k]=String(v)},removeItem:k=>{delete mem[k]},get length(){return Object.keys(mem).length},key:i=>Object.keys(mem)[i]??null};
const src=path.join(__dirname,"..");
JSON.parse(fs.readFileSync(path.join(src,"manifest.json"))).forEach(f=>vm.runInThisContext(fs.readFileSync(path.join(src,f+".js"),"utf8"),{filename:f}));
/* tiny fake browser: lets us render pages and call the API client from Node (no DOM library, no packages) */
const el={innerHTML:"",addEventListener(){}};
global.document={querySelector:()=>el};
global.location={search:"",pathname:"/login.html",hostname:"example.com"};
["ui/components/ui","ui/pages/pages","api/httpClient","api/remoteApi","api/mockApi","api/privateState"].forEach(f=>vm.runInThisContext(fs.readFileSync(path.join(src,f+".js"),"utf8"),{filename:f}));
let pass=0,bad=0;
const t=(n,f)=>{AppStorage.clear();AppState.set("currentUser",null);try{f();pass++;console.log("ok   "+n)}catch(e){bad++;console.log("FAIL "+n+": "+e.message)}};
const eq=(a,b)=>{if(a!==b)throw new Error(JSON.stringify(a)+" !== "+JSON.stringify(b))},ok=(c,m)=>{if(!c)throw new Error(m||"assertion failed")};
const as=e=>{const u=Data.find("users",x=>x.email===e+"@art4sells.test")[0];return{id:u.id,name:u.name,email:u.email,role:u.role}};   /* fixture lookup only: mock login no longer exists */
const search=o=>ArtworkService.searchArtworks(o);
t("Validation",()=>{const r=Validation.validateArtwork({title:"",price:0,cat:"x",type:"?"});ok(!r.valid&&r.errors.title&&r.errors.price);ok(Validation.validateArtwork({title:"A",price:10,cat:"3D Art",type:"LIMITED"}).valid);ok(Validation.validateEmail("bad"))});
t("Auth (mock is disabled: no password, no login)",()=>{ok(!AuthService.register({name:"Z",email:"z@x.io",password:"Abcdef12!",confirm:"Abcdef12!",role:"ADMIN"}).ok,"no self-admin");ok(!AuthService.register({name:"Zed",email:"zed@x.io",password:"Abcdef12!",confirm:"Abcdef12!",role:"ARTIST"}).ok,"mock cannot register");eq(AuthService.getCurrentUser(),null);ok(!AuthService.login({email:"no@x.io",password:"Abcdef12!"}).ok);AuthService.logout();eq(AuthService.getCurrentUser(),null)});
t("RBAC",()=>{ok(!RBAC.hasPermission(as("mika"),"artwork.approve"));ok(RBAC.hasPermission(as("admin"),"audit.view"));let c;try{RBAC.requirePermission(as("buyer"),"ip.block")}catch(e){c=e.code}eq(c,"FORBIDDEN")});
t("Artwork CRUD + approval",()=>{const m=as("mika"),a=as("admin"),d={title:"Test Piece",price:300,cat:"Illustration",type:"UNLIMITED"};
 ok(!ArtworkService.createArtwork(d,as("buyer")).ok);const w=ArtworkService.createArtwork(d,m).artwork;eq(w.status,"DRAFT");
 ok(ArtworkService.updateArtwork(w.id,{price:350},m).ok);ok(!ArtworkService.updateArtwork(w.id,{price:-1},m).ok);
 ok(!ArtworkService.approveArtwork(w.id,a).ok,"DRAFT cannot jump to APPROVED");ok(ArtworkService.submitForApproval(w.id,m).ok);
 ok(!ArtworkService.approveArtwork(w.id,m).ok,"artist cannot approve");ok(ArtworkService.approveArtwork(w.id,a).ok);ok(ArtworkService.getArtwork(w.id));
 ok(ArtworkService.deleteArtwork(w.id,m).ok);eq(ArtworkService.getArtwork(w.id),null)});
t("Search",()=>{eq(search({query:"koi"}).total,1);eq(search({query:"kenji",type:"artist"}).total,3);eq(search({query:"night",type:"tag"}).total,2)});
t("Filter",()=>{eq(search({filters:{category:"3D Art"}}).total,2);eq(search({filters:{maxPrice:500}}).total,1);eq(search({filters:{saleType:"UNLIMITED"}}).total,5);eq(search({filters:{minRating:4.9}}).total,3)});
t("Sort",()=>{eq(search({sort:"priceAsc"}).items[0].price,450);eq(search({sort:"priceDesc"}).items[0].price,2200)});
t("Pagination",()=>{const p=search({pageSize:5,page:3});eq(p.totalPages,3);eq(p.items.length,2);eq(search({pageSize:5,page:99}).page,3)});
t("Cart",()=>{ok(CartService.addToCart("w1").ok);ok(!CartService.addToCart("w8").ok,"sold");ok(!CartService.addToCart("w6").ok,"pending payment");CartService.addToCart("w3");CartService.addToCart("w3");eq(CartService.getCart().w3,2);eq(CartService.calculateSubtotal(),1200+650*2);CartService.clearCart();eq(CartService.count(),0)});
t("Wishlist",()=>{WishlistService.addToWishlist("w1");ok(WishlistService.isWishlisted("w1"));WishlistService.removeFromWishlist("w1");ok(!WishlistService.isWishlisted("w1"))});
t("Order states",()=>{const b=as("buyer");CartService.addToCart("w2");const o=OrderService.createOrder(b,CartService.getCart()).order;eq(o.status,"PENDING_PAYMENT");
 eq(ArtworkService.getArtwork("w2").availability,"Processing");ok(!OrderService.createOrder(b,{w2:1}).ok,"no double purchase");
 ok(OrderService.expireOrder(o.id).ok);eq(ArtworkService.getArtwork("w2").availability,"Available");ok(!OrderService.advance(o.id,"PAID",null).ok,"EXPIRED cannot be PAID");
 const o2=OrderService.createOrder(b,{w2:1}).order;["PAYMENT_VERIFIED","PAID"].forEach(s=>ok(OrderService.advance(o2.id,s,b).ok));eq(ArtworkService.getArtwork("w2").availability,"Sold")});
t("Review permission",()=>{const b=as("buyer");ok(ReviewService.canUserReview(b,"w8"));ok(!ReviewService.canUserReview(b,"w1"),"not purchased");ok(!ReviewService.createReview(b,{artworkId:"w8",rating:9,text:"x"}).ok);ok(ReviewService.createReview(b,{artworkId:"w8",rating:4,text:"Great detail"}).ok);ok(!ReviewService.canUserReview(b,"w8"),"once only");eq(ReviewService.calculateAverageRating(ReviewService.getArtworkReviews("w8")),4.5)});
t("Commission states",()=>{const b=as("buyer"),m=as("mika"),j=CommissionService.submitCommissionBrief(b,"cl_a1_0","A fox ranger holding a lantern").job;
 ["PAYMENT_PENDING","PAYMENT_VERIFIED","ARTIST_REVIEW"].forEach(s=>ok(CommissionService.advanceCommission(j.id,s,b,"either").ok));
 ok(!CommissionService.completeCommission(j.id,b).ok,"ARTIST_REVIEW cannot complete");ok(!CommissionService.acceptCommission(j.id,b).ok,"buyer cannot accept");ok(CommissionService.acceptCommission(j.id,m).ok);
 ok(CommissionService.startCommission(j.id,m).ok);ok(CommissionService.advanceCommission(j.id,"DELIVERED",m,"artist").ok);ok(CommissionService.completeCommission(j.id,b).ok);
 ok(!StateMachine.canTransition("COMPLETED","ACCEPTED",Const.COMMISSION))});
t("Audit log",()=>{as("buyer");ArtworkService.approveArtwork("w13",as("admin"));eq(AuditLog.list("USER_LOGIN").length,0,"mock login is disabled, so it must not log anyone in");eq(AuditLog.list("ARTWORK_APPROVED").length,1)});
/* ---------- Phase 3.5b: login authentication hardening + password policy ---------- */
const DEMO=["admin","mika","buyer","kenji","nara","lumi","ton"],later=[],ta=(n,f)=>later.push([n,f]);
const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):[path.join(d,e.name)]);
t("Password policy (UI check)",()=>{
 ["abcdefgh","ABCDEFGH","12345678","Abcdefgh","Abcdef12","abcdef1!","ABCDEF1!","Abc!","abcdef12","Abcdef12 ",""].forEach(p=>ok(Validation.validatePassword(p),"must reject: "+JSON.stringify(p)));
 ["Abcd1234!","HelloWorld9@","TestPass1#","Abcdef12!"," Abcd1234! "].forEach(p=>eq(Validation.validatePassword(p),"","must accept: "+JSON.stringify(p)));
 eq(Validation.validatePassword("Aa1!"+"x".repeat(4)),"");eq(Validation.validatePassword("Aa1!"+"x".repeat(124)),"");           /* 8 and 128 characters */
 ok(Validation.validatePassword("Aa1!xxx"),"7 chars");ok(Validation.validatePassword("Aa1!"+"x".repeat(125)),"129 chars");
 ok(Validation.validatePassword(undefined));ok(Validation.validatePassword(12345678));
 eq(Validation.validateRegistration({name:"Zed",email:"z@x.io",password:"Abcdef12!",confirm:"Abcdef12! ",role:"USER"}).errors.confirm,"Passwords do not match")});
t("Login form check has no password policy",()=>{
 ok(Validation.validateLogin({email:"a@b.co",password:"abc"}).valid,"a short/weak password must still reach the server (login only verifies)");
 ok(!Validation.validateLogin({email:"a@b.co",password:""}).valid);ok(!Validation.validateLogin({email:"a@b.co",password:12345678}).valid);ok(!Validation.validateLogin({email:"bad",password:"x"}).valid)});
t("Mock auth: no email-only login for ANY demo account",()=>{
 DEMO.forEach(n=>["anything123","12345678","Demo1234!","Demo1234","","x"].forEach(p=>ok(!AuthService.login({email:n+"@art4sells.test",password:p}).ok,"mock login must fail: "+n+" / "+p)));
 eq(AuthService.getCurrentUser(),null);eq(AuditLog.list("USER_LOGIN").length,0)});
t("No email-based authentication bypass and no 'Any 8+' text in the source",()=>{
 const files=[...walk(src),...walk(path.join(src,"..","public"))].filter(f=>/\.(js|html)$/.test(f)&&!f.includes(path.join("src","test")));
 files.forEach(f=>{const c=fs.readFileSync(f,"utf8");
  ok(!/Any 8\+/i.test(c),f+" still says 'Any 8+ character password'");
  ok(!/endsWith\(["']@art4sells|isDemoEmail|knownTestEmail|===\s*["']admin@art4sells/.test(c),f+" has an email-based bypass")})});
t("Login page (real backend): Forgot password link under the password field",()=>{
 A4S.mode="api";location.hostname="example.com";A4S.pages.login();const h=el.innerHTML;
 ok(h.includes('href="forgot.html"')&&h.includes("Forgot password?"),"link missing");
 ok(h.indexOf('name="password"')<h.indexOf("forgot.html"),"link must come after the password field");
 ok(!/Any 8\+/i.test(h));ok(!h.includes("Demo1234!")&&!h.includes("art4sells.test"),"no demo credentials on a deployed host");
 location.hostname="localhost";A4S.pages.login();ok(el.innerHTML.includes("Demo1234!"),"dev machines show the real demo password");location.hostname="example.com"});
t("Forgot password page exists and is routed",()=>{
 const html=fs.readFileSync(path.join(src,"..","public","forgot.html"),"utf8");ok(html.includes('data-page="forgot"'));eq(typeof A4S.pages.forgot,"function")});
t("Register page lists the password requirements",()=>{
 A4S.mode="api";A4S.pages.register();const h=el.innerHTML;
 ["At least 8 characters","One uppercase letter","One lowercase letter","One number","One special character"].forEach(r=>ok(h.includes(r),"missing: "+r));
 ok(h.includes('name="confirm"'),"confirm password field")});
t("MOCK mode: login/register pages say the real backend is required (no fake form)",()=>{
 A4S.mode="mock";["login","register"].forEach(pg=>{A4S.pages[pg]();const h=el.innerHTML;
  ok(h.includes("real backend"),pg);ok(!h.includes('type="password"'),pg+" must not show a password form");ok(!/Any 8\+/i.test(h))});A4S.mode="api"});
const fetchSpy=reply=>{const calls=[];global.fetch=async(u,init)=>{calls.push({url:u,body:init.body?JSON.parse(init.body):null});return{ok:true,status:200,json:async()=>reply}};return calls};
ta("API client: register sends confirm_password, rejects weak/mismatched passwords before any request",async()=>{
 A4S.config={apiBase:"/api"};const calls=fetchSpy({token:"t",user:{id:"u9",name:"N",email:"n@x.io",role:"USER"}});
 const reg=d=>A4S.remoteApi.auth.register(Object.assign({name:"Nina",email:"n@x.io",role:"USER"},d));
 ok(!(await reg({password:"abcdef12",confirm:"abcdef12"})).ok);ok(!(await reg({password:"Abcdef12!",confirm:"Abcdef12!x"})).ok);eq(calls.length,0,"nothing may be sent");
 ok((await reg({password:"Abcdef12! ",confirm:"Abcdef12! "})).ok);eq(calls.length,1);
 eq(calls[0].body.password,"Abcdef12! ","password must reach the server untouched (no trim)");eq(calls[0].body.confirm_password,"Abcdef12! ")});
ta("API client: login sends the password exactly as typed",async()=>{
 A4S.config={apiBase:"/api"};const calls=fetchSpy({token:"t",user:{id:"u9",name:"N",email:"n@x.io",role:"USER"}});
 await A4S.remoteApi.auth.login({email:"n@x.io",password:" Pa ss! "});eq(calls[0].url,"/api/login");eq(calls[0].body.password," Pa ss! ")});
ta("API client: change/reset password use the same policy",async()=>{
 A4S.config={apiBase:"/api"};const calls=fetchSpy({message:"ok"});
 ok(!(await A4S.remoteApi.password.change({current:"x",next:"abcdef12",confirm:"abcdef12"})).ok);ok(!(await A4S.remoteApi.password.reset({token:"t",next:"abcdef12",confirm:"abcdef12"})).ok);eq(calls.length,0);
 ok((await A4S.remoteApi.password.change({current:"x",next:"Abcdef12!",confirm:"Abcdef12!"})).ok);ok((await A4S.remoteApi.password.reset({token:"t",next:"Abcdef12!",confirm:"Abcdef12!"})).ok);eq(calls.length,2)});
ta("Mock API: login/register are refused",async()=>{
 ok(!(await A4S.mockApi.auth.login({email:"buyer@art4sells.test",password:"anything123"})).ok);ok(!(await A4S.mockApi.auth.register({name:"Zed",email:"zed@x.io",password:"Abcdef12!",confirm:"Abcdef12!",role:"USER"})).ok);eq(AuthService.getCurrentUser(),null)});
ta("Entering MOCK mode drops any old saved login (stale mock admin session)",async()=>{
 AppState.set("currentUser",{id:"ad1",name:"Site Admin",email:"admin@art4sells.test",role:"ADMIN"});AppStorage.set("token","stale");
 global.location={search:"?mode=mock",pathname:"/index.html",hostname:"example.com"};
 vm.runInThisContext(fs.readFileSync(path.join(src,"api/index.js"),"utf8"),{filename:"api/index"});await A4S.ready;
 eq(A4S.mode,"mock");eq(AuthService.getCurrentUser(),null,"old mock session must not stay logged in");eq(AppStorage.get("token",null),null)});
/* ---- Finale Prototype Part 1: cookie session, no fake backend, XSS-safe rendering ---- */
const spyFull=reply=>{const calls=[];global.fetch=async(u,init)=>{calls.push({url:u,init:init||{}});return{ok:true,status:200,json:async()=>reply}};return calls};
ta("Login uses the HttpOnly cookie: no token stored, no Authorization header, user kept in memory only",async()=>{
 A4S.config={apiBase:"/api"};
 const calls=spyFull({user:{id:"u1",name:"Pim",email:"buyer@art4sells.test",role:"USER"}});
 const r=await A4S.remoteApi.auth.login({email:"buyer@art4sells.test",password:"Demo1234!"});
 ok(r.ok);eq(AuthService.getCurrentUser().id,"u1");
 eq(calls[0].init.credentials,"same-origin");ok(!("Authorization" in calls[0].init.headers),"no Authorization header");
 ok(Object.keys(mem).every(k=>k.toLowerCase().indexOf("token")===-1&&k.indexOf("currentUser")===-1),"nothing about the login in localStorage");
 eq(AppStorage.get("token",null),null);eq(AppStorage.get("currentUser",null),null);ok(A4S.http.signedIn());
 spyFull({});const out=await A4S.remoteApi.auth.logout();ok(out.ok);eq(AuthService.getCurrentUser(),null);ok(!A4S.http.signedIn())});
ta("Cross-origin API address sends the cookie only when explicitly configured",async()=>{
 A4S.config={apiBase:"http://api.example.com/api"};let calls=spyFull({user:null});await A4S.http.get("/health");eq(calls[0].init.credentials,"include");
 A4S.config={apiBase:"/api"};calls=spyFull({user:null});await A4S.http.get("/health");eq(calls[0].init.credentials,"same-origin")});
ta("A 401 from the server drops the in-memory user and the private page state",async()=>{
 A4S.config={apiBase:"/api"};AppState.set("currentUser",{id:"u1",name:"P",email:"p@x.io",role:"USER"});A4S.priv.userId="u1";A4S.priv.unread=3;
 global.fetch=async()=>({ok:false,status:401,json:async()=>({error:{code:"UNAUTHORIZED",message:"x"}})});
 const r=await A4S.http.get("/me");ok(!r.ok);eq(AuthService.getCurrentUser(),null);eq(A4S.priv.unread,0)});
ta("A leftover login token from an older version is removed from localStorage at start",async()=>{
 AppStorage.set("token","old-token-from-phase-3");AppStorage.set("currentUser",{id:"ad1",name:"Site Admin",email:"a@x.io",role:"ADMIN"});
 global.location={search:"",pathname:"/index.html",hostname:"art4sells.example.app"};
 global.fetch=async()=>{throw new Error("down")};
 vm.runInThisContext(fs.readFileSync(path.join(src,"api/index.js"),"utf8"),{filename:"api/index"});await A4S.ready;
 eq(AppStorage.get("token",null),null);eq(AppStorage.get("currentUser",null),null);eq(AuthService.getCurrentUser(),null)});
ta("Deployed site + backend down: no mock fallback and no fake login (private actions say unavailable)",async()=>{
 global.location={search:"",pathname:"/index.html",hostname:"art4sells.example.app"};global.fetch=async()=>{throw new Error("network down")};
 vm.runInThisContext(fs.readFileSync(path.join(src,"api/index.js"),"utf8"),{filename:"api/index"});await A4S.ready;
 eq(A4S.mode,"api");eq(A4S.config.allowMockFallback,false);ok(A4S.backendDown===true,"backendDown flag");
 const r=await A4S.api.auth.login({email:"admin@art4sells.test",password:"Demo1234!"});
 ok(!r.ok);eq(r.code,"NETWORK");eq(AuthService.getCurrentUser(),null);
 const w=await A4S.api.cart.add("w1",1);ok(!w.ok,"private action fails instead of pretending")});
ta("Local computer + backend down: the classroom MOCK fallback is still allowed (read-only, no login)",async()=>{
 global.location={search:"",pathname:"/index.html",hostname:"localhost"};global.fetch=async()=>{throw new Error("network down")};
 vm.runInThisContext(fs.readFileSync(path.join(src,"api/index.js"),"utf8"),{filename:"api/index"});await A4S.ready;
 eq(A4S.mode,"mock");ok(!(await A4S.api.auth.login({email:"admin@art4sells.test",password:"Demo1234!"})).ok);eq(AuthService.getCurrentUser(),null)});
ta("XSS payloads in user-generated text are escaped by every renderer that builds HTML",async()=>{
 const bad=['<script>alert(1)</script>','<img src=x onerror=alert(1)>','"><svg onload=alert(1)>',"javascript:alert(1)","'><b>x</b>",'</title><script>1</script>','" onmouseover="alert(1)'];
 const U=A4S.ui,tags=h=>(h.match(/</g)||[]).length;   /* an injection must never add a single extra tag: compare with a harmless baseline */
 const card=v=>U.card({id:"w1",title:v,artist:"a1",artistName:v,cat:v,price:10,rating:4,type:"LIMITED",status:"APPROVED",seed:1,tags:[v]});
 const panel=v=>A4S.pages.dmPanel({counts:{[v]:1},auto_included:[v],preserve_admins:true},"clear");
 const baseCard=tags(card("harmless")),basePanel=tags(panel("harmless"));
 bad.forEach(b=>{
  const c=card(b),pl=panel(b);
  ok(c.indexOf(b)===-1||b==="javascript:alert(1)","raw payload appears in card: "+b);
  ok(pl.indexOf(b)===-1||b==="javascript:alert(1)","raw payload appears in admin panel: "+b);
  eq(tags(c),baseCard,"card gained extra tags for "+b);eq(tags(pl),basePanel,"admin panel gained extra tags for "+b);
  ok(c.indexOf('" onmouseover')===-1&&c.indexOf("'><b>")===-1,"attribute break-out in card for "+b);
  ok(U.esc(b).indexOf("<")===-1&&U.esc(b).indexOf(">")===-1&&U.esc(b).indexOf('"')===-1&&U.esc(b).indexOf("'")===-1,"esc() left a dangerous character in "+b)});
 ok(card("javascript:alert(1)").indexOf('href="javascript:')===-1,"user text must never become a link target")});
ta("Source has no eval / new Function / document.write and keeps localStorage inside core/storage.js only",async()=>{
 const strip=t=>t.replace(/\/\*[\s\S]*?\*\//g,"").replace(/(^|[^:"'])\/\/[^\n]*/g,"$1");
 const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?(e.name==="test"?[]:walk(path.join(d,e.name))):[path.join(d,e.name)]);
 const files=walk(src).filter(f=>f.endsWith(".js")).concat(walk(path.join(src,"..","public")).filter(f=>f.endsWith(".html")||f.endsWith(".js")));
 files.forEach(f=>{const t=strip(fs.readFileSync(f,"utf8")),rel=path.relative(path.join(src,".."),f).split(path.sep).join("/");
  ok(!/\beval\s*\(|new\s+Function\s*\(|document\.write(ln)?\s*\(/.test(t),"dangerous call in "+rel);
  ok(!/sessionStorage|document\.cookie/.test(t),"storage/cookie API in "+rel);
  if(rel!=="src/core/storage.js")ok(!/localStorage/.test(t),"localStorage outside core/storage.js: "+rel)})});
(async()=>{for(const[n,f]of later){AppStorage.clear();AppState.set("currentUser",null);try{await f();pass++;console.log("ok   "+n)}catch(e){bad++;console.log("FAIL "+n+": "+e.message)}}
 console.log(pass+" passed, "+bad+" failed");process.exit(bad?1:0)})();
