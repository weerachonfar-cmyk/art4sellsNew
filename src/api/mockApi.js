/* MOCK implementation (Phase 2 prototype): wraps the old synchronous services so they look like the real API.
   Used ONLY when the backend is unreachable (development fallback) or when forced with ?mode=mock.
   Data lives in localStorage and is NOT the real data - the page shows a "MOCK MODE" banner while this is active. */
A4S.mockApi=(function(){
 var A={},me=function(){return AuthService.getCurrentUser()};
 var vm=function(w){var a=AuthService.getUser(w.artist);return Object.assign({},w,{artistName:a?a.name:"",catId:w.cat})};
 var artist=function(u){return{id:u.id,name:u.name,headline:u.headline||"",bio:u.bio||"",rating:u.rating||0,followers:u.followers||0,commission:!!u.commission}};
 var fromForm=function(d){return{title:d.title,price:d.price,cat:d.category,type:d.sale_type,tags:typeof d.tags==="string"?d.tags.split(",").map(function(t){return t.trim()}).filter(Boolean):d.tags,desc:d.description}};
 var wrap=function(r,key){return r.ok?Object.assign({ok:true},key?{[key]:vm(r[key])}:{}):r};
 var slice=function(list,p){var size=15,tp=Math.max(1,Math.ceil(list.length/size)),pg=Math.min(Math.max(1,+p||1),tp);return{ok:true,items:list.slice((pg-1)*size,pg*size),total:list.length,page:pg,pageSize:size,totalPages:tp}};

 A.auth={
  register:async function(d){return AuthService.register(d)},
  login:async function(d){return AuthService.login(d)},
  logout:async function(){AuthService.logout();A4S.priv.clear();return{ok:true}},
  me:async function(){return{ok:true,user:AuthService.getCurrentUser(),passwordChangeAvailableAt:null}}
 };
 A.categories={list:async function(){return{ok:true,items:A4S.cats.map(function(c){return{id:c,name:c}})}}};
 A.artists={
  list:async function(){return{ok:true,items:AuthService.getArtists().map(artist)}},
  get:async function(id){var u=AuthService.getUser(id);return u&&u.role==="ARTIST"?{ok:true,artist:artist(u)}:{ok:false,status:404,error:"Artist not found"}}
 };
 A.artworks={
  search:async function(o){var r=ArtworkService.searchArtworks(o);return Object.assign({ok:true},r,{items:r.items.map(vm)})},
  get:async function(id){var w=ArtworkService.getArtwork(id);return w?{ok:true,artwork:vm(w)}:{ok:false,status:404,error:"Artwork not found"}},
  mine:async function(){var u=me();return{ok:true,items:Data.find("artworks",function(w){return u&&w.artist===u.id}).map(vm)}},
  submissions:async function(){return{ok:true,items:ArtworkService.getSubmissions().map(vm)}},
  create:async function(d){return wrap(ArtworkService.createArtwork(fromForm(d),me()),"artwork")},
  update:async function(id,d){return wrap(ArtworkService.updateArtwork(id,fromForm(d),me()),"artwork")},
  remove:async function(id){return ArtworkService.deleteArtwork(id,me())},
  submit:async function(id){return ArtworkService.submitForApproval(id,me())},
  approve:async function(id){return ArtworkService.approveArtwork(id,me())},
  reject:async function(id){return ArtworkService.rejectArtwork(id,me())}
 };
 /* Private data in MOCK mode is stored per user id ("mock_cart_u1"), so two users on one browser never share it.
  Nothing is created for a visitor who is not logged in. */
 var NEED_LOGIN={ok:false,status:401,error:"Please log in first"};
 var store=function(name){var u=me();return u?"mock_"+name+"_"+u.id:null};
 var read=function(name,fallback){var k=store(name);return k?AppState.get(k,fallback):fallback};
 var write=function(name,value){AppState.set(store(name),value)};
 var artworkOf=function(id){var w=ArtworkService.getArtwork(id);return w?vm(w):null};
 A.cart={
  get:async function(){
   if(!me())return NEED_LOGIN;
   var map=read("cart",{}),items=[],count=0,total=0;
   Object.keys(map).forEach(function(id){var w=artworkOf(id);if(!w)return;var ok=w.availability==="Available",line=w.price*map[id];
    items.push({id:id,artworkId:id,quantity:map[id],lineTotal:line,purchasable:ok,artwork:w});count+=map[id];if(ok)total+=line});
   return{ok:true,cart:{items:items,count:count,total:total}};
  },
  add:async function(id,qty){
   if(!me())return NEED_LOGIN;
   var w=artworkOf(id);
   if(!w)return{ok:false,status:404,error:"Artwork not found"};
   if(w.availability!=="Available")return{ok:false,status:409,error:"This artwork cannot be bought right now"};
   var map=read("cart",{});map[id]=w.type==="LIMITED"?1:Math.min(99,(map[id]||0)+(qty||1));write("cart",map);return{ok:true};
  },
  setQty:async function(id,q){if(!me())return NEED_LOGIN;var map=read("cart",{});if(map[id]===undefined)return{ok:false,status:404,error:"Not found"};map[id]=q;write("cart",map);return{ok:true}},
  remove:async function(id){if(!me())return NEED_LOGIN;var map=read("cart",{});delete map[id];write("cart",map);return{ok:true}},
  checkout:async function(){if(!me())return NEED_LOGIN;var r=OrderService.createOrder(me(),read("cart",{}));if(r.ok)write("cart",{});return r}
 };
 A.wishlist={
  list:async function(){if(!me())return NEED_LOGIN;return{ok:true,items:read("wishlist",[]).map(artworkOf).filter(Boolean).map(function(w){return{id:w.id,artworkId:w.id,artwork:w}})}},
  add:async function(id){if(!me())return NEED_LOGIN;var l=read("wishlist",[]);if(l.indexOf(id)<0)l.push(id);write("wishlist",l);return{ok:true,id:id}},
  remove:async function(id){if(!me())return NEED_LOGIN;write("wishlist",read("wishlist",[]).filter(function(x){return x!==id}));return{ok:true}}
 };
 A.follows={
  list:async function(){if(!me())return NEED_LOGIN;return{ok:true,items:read("follows",[]).map(function(id){return{id:id,artistId:id}})}},
  add:async function(id){if(!me())return NEED_LOGIN;var l=read("follows",[]);if(l.indexOf(id)<0)l.push(id);write("follows",l);return{ok:true,id:id}},
  remove:async function(id){if(!me())return NEED_LOGIN;write("follows",read("follows",[]).filter(function(x){return x!==id}));return{ok:true}}
 };
 A.notifications={
  unread:async function(){return me()?{ok:true,unread:0}:NEED_LOGIN},
  list:async function(){return me()?{ok:true,items:[],unread:0}:NEED_LOGIN},
  read:async function(){return{ok:true}},readAll:async function(){return{ok:true}}
 };
 A.reviews={
  list:async function(id){return{ok:true,items:ReviewService.getArtworkReviews(id).map(function(r){var u=AuthService.getUser(r.userId);return{id:r.id,user:u?u.name:"",rating:r.rating,text:r.text}})}},
  eligibility:async function(id){var u=me();return{ok:true,eligible:!!u&&ReviewService.canUserReview(u,id),reason:"You need a completed order for this artwork."}},
  create:async function(d){return ReviewService.createReview(me(),{artworkId:d.artworkId,rating:d.rating,text:d.text})}
 };
 A.dashboard={summary:async function(){var s=DashboardService.summary(),paid=Data.find("orders",function(o){return o.status==="PAID"||o.status==="COMPLETED"});
  return{ok:true,users:s.users,artists:s.artists,artworks:s.artworks,pending:ArtworkService.getSubmissions().filter(function(w){return w.status==="PENDING_APPROVAL"}).length,
   orders:s.orders,sales:paid.reduce(function(t,o){return t+o.total},0),reviews:Data.getAll("reviews").length}}};
 var needBackend=async function(){return{ok:false,error:"This feature needs the real backend (mock mode has no user management)."}};
 A.users={list:needBackend,ban:needBackend,unban:needBackend};
 A.password={change:needBackend,forgot:needBackend,resend:needBackend,verify:needBackend,reset:needBackend};
 A.dataAdmin={previewClear:needBackend,clear:needBackend,previewReset:needBackend,reset:needBackend};
 A.logs={list:async function(p){return slice(AuditLog.list().slice().reverse().map(function(e){return{timestamp:e.timestamp,actor_id:e.actorId,action:e.action,target_type:e.targetType,target_id:e.targetId}}),p)}};
 return A;
})();
