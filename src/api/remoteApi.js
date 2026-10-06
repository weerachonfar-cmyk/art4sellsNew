/* REAL backend implementation of the app's data interface (A4S.api). Every method is async and returns a Result:
   {ok:true, ...data}  or  {ok:false, error, errors}.  No mock data is used anywhere in this file. */
A4S.remoteApi=(function(){
 var H=A4S.http,A={};
 var AV={AVAILABLE:"Available",SOLD:"Sold",PROCESSING:"Processing",NOT_FOR_SALE:"Not for sale"};
 var SORT={newest:"newest",oldest:"oldest",priceAsc:"price_asc",priceDesc:"price_desc",rating:"rating"};
 var SEARCH_IN={artwork:"title",artist:"artist",tag:"tag"};
 /* backend record -> the shape the UI already renders (same field names as the Phase 2 mock) */
 var toArtwork=function(w){return{id:w.id,title:w.title,artist:w.artist_id,artistName:w.artist_name||"",cat:w.category_name||w.category,
  catId:w.category,price:w.price,rating:w.rating,type:w.sale_type,status:w.status,tags:w.tags||[],desc:w.description||"",
  seed:w.preview_seed||0,createdAt:w.created_at,submittedAt:w.submitted_at,rejectReason:w.reject_reason,
  availability:AV[w.availability]||w.availability}};
 var toArtist=function(u){return{id:u.id,name:u.name,headline:u.headline||"",bio:u.bio||"",rating:u.rating||0,followers:u.followers||0,commission:!!u.accepts_commissions}};
 var page=function(d,map){return{ok:true,items:d.items.map(map||function(x){return x}),total:d.total,page:d.page,pageSize:d.page_size,totalPages:d.total_pages}};
 var session=function(d){AppState.set("currentUser",{id:d.user.id,name:d.user.name,email:d.user.email,role:d.user.role});return{ok:true,user:AppState.get("currentUser",null)}};
 var body=function(d){return{title:d.title,price:d.price,category:d.category,sale_type:d.sale_type,tags:d.tags,description:d.description}};

 /* UX pre-check for every place a NEW password is typed (register / change / reset): policy first, then exact match. The backend validates again. */
 var pwCheck=function(next,confirm,field,cfield){
  var e=Validation.validatePassword(next);if(e){var a={};a[field]=e;return{ok:false,error:e,errors:a}}
  if(confirm!==next){var b={};b[cfield]="Passwords do not match";return{ok:false,error:"Passwords do not match",errors:b}}
  return null};
 A.auth={
  register:async function(d){
   var bad=pwCheck(d.password,d.confirm,"password","confirm");if(bad)return bad;
   var r=await H.post("/register",{name:d.name,email:d.email,password:d.password,confirm_password:d.confirm,role:d.role});
   return r.ok?session(r.data):r;
  },
  login:async function(d){var r=await H.post("/login",{email:d.email,password:d.password});return r.ok?session(r.data):r},
  logout:async function(){   /* the server invalidates the session and clears the cookie; the browser then drops every private copy */
   if(H.signedIn())await H.post("/logout");
   AppState.set("currentUser",null);A4S.devTools=false;A4S.priv.clear();return{ok:true}},
  me:async function(){   /* ask the server who the cookie belongs to (the in-memory user is only for drawing the header) */
   var r=await H.get("/me");
   if(r.ok){var u=r.data.user;AppState.set("currentUser",{id:u.id,name:u.name,email:u.email,role:u.role});A4S.devTools=!!r.data.dev_tools;
    return{ok:true,user:u,passwordChangeAvailableAt:r.data.password_change_available_at}}
   AppState.set("currentUser",null);A4S.devTools=false;
   return{ok:r.status===401,user:null,error:r.error};
  }
 };
 A.devTools={mailbox:async function(){var r=await H.get("/dev/mailbox");return r.ok?{ok:true,items:r.data.items,warning:r.data.warning}:r}};   /* admin only; 404 unless the server runs with A4S_DEV_TOOLS=true */
 A.categories={list:async function(){var r=await H.get("/categories");return r.ok?{ok:true,items:r.data.items}:r}};
 A.artists={
  list:async function(){var r=await H.get("/artists");return r.ok?{ok:true,items:r.data.items.map(toArtist)}:r},
  get:async function(id){var r=await H.get("/artists/"+encodeURIComponent(id));return r.ok?{ok:true,artist:toArtist(r.data)}:r}
 };
 A.artworks={
  search:async function(o){
   o=o||{};var f=o.filters||{};
   var r=await H.get("/artworks",{q:o.query,search_in:SEARCH_IN[o.type],category:f.category,min_rating:f.minRating,max_price:f.maxPrice,
    min_price:f.minPrice,sale_type:f.saleType,artist_id:f.artist,sort:SORT[o.sort]||"newest",page:o.page||1,page_size:o.pageSize||12});
   return r.ok?page(r.data,toArtwork):r;
  },
  get:async function(id){var r=await H.get("/artworks/"+encodeURIComponent(id));return r.ok?{ok:true,artwork:toArtwork(r.data)}:r},
  mine:async function(){var r=await H.get("/artworks",{mine:"true",page_size:50,sort:"newest"});return r.ok?page(r.data,toArtwork):r},
  submissions:async function(){var r=await H.get("/artworks",{submitted:"true",page_size:50,sort:"newest"});return r.ok?page(r.data,toArtwork):r},
  create:async function(d){var r=await H.post("/artworks",body(d));return r.ok?{ok:true,artwork:toArtwork(r.data)}:r},
  update:async function(id,d){var r=await H.put("/artworks/"+encodeURIComponent(id),body(d));return r.ok?{ok:true,artwork:toArtwork(r.data)}:r},
  remove:async function(id){var r=await H.del("/artworks/"+encodeURIComponent(id));return r.ok?{ok:true}:r},
  /* image upload: the backend takes JSON {filename, content_type, data_base64}. 3 MB cap because Vercel limits a request to ~4.5 MB and base64 adds a third. */
  checkFile:function(file){
   var n=String(file&&file.name||""),ext=n.indexOf(".")>=0?n.split(".").pop().toLowerCase():"";
   if(["png","jpg","jpeg","webp"].indexOf(ext)<0)return"Only PNG, JPG or WebP images are allowed";
   if(!file.size)return"The selected file is empty";
   if(file.size>3*1024*1024)return"Image must be 3 MB or smaller";
   return""},
  uploadFile:async function(id,file){
   var bad=A.artworks.checkFile(file);if(bad)return{ok:false,error:bad,errors:{}};
   var ext=String(file.name).split(".").pop().toLowerCase(),mime=ext==="png"?"image/png":ext==="webp"?"image/webp":"image/jpeg",b64;
   try{b64=await new Promise(function(res,rej){var fr=new FileReader();fr.onload=function(){var s=String(fr.result);res(s.slice(s.indexOf(",")+1))};fr.onerror=function(){rej(new Error("read"))};fr.readAsDataURL(file)})}
   catch(e){return{ok:false,error:"Could not read the selected file",errors:{}}}
   /* the name sent is generic on purpose: the server never uses it for storage and rejects names containing ".." or slashes */
   var r=await H.request("POST","/artworks/"+encodeURIComponent(id)+"/file",{body:{filename:"artwork."+ext,content_type:mime,data_base64:b64},timeout:30000});
   return r.ok?{ok:true,files:r.data.files}:r},
  submit:function(id){return A.artworks._act(id,"submit")},
  approve:function(id){return A.artworks._act(id,"approve")},
  reject:function(id){return A.artworks._act(id,"reject")},
  _act:async function(id,verb){var r=await H.post("/artworks/"+encodeURIComponent(id)+"/"+verb);return r.ok?{ok:true}:r}
 };
 var toCartView=function(c){return{count:c.count,total:c.total,items:c.items.map(function(i){return{id:i.id,artworkId:i.artwork_id,quantity:i.quantity,lineTotal:i.line_total,purchasable:i.purchasable,artwork:toArtwork(i.artwork)}})}};
 /* private data: the server derives the owner from the session cookie - the browser never sends a user id */
 A.cart={
  get:async function(){var r=await H.get("/cart");return r.ok?{ok:true,cart:toCartView(r.data)}:r},
  add:async function(artworkId,qty){var r=await H.post("/cart",{artwork_id:artworkId,quantity:qty||1});return r.ok?{ok:true,created:r.data.created}:r},
  setQty:async function(itemId,q){var r=await H.put("/cart/"+encodeURIComponent(itemId),{quantity:q});return r.ok?{ok:true}:r},
  remove:async function(itemId){var r=await H.del("/cart/"+encodeURIComponent(itemId));return r.ok?{ok:true}:r},
  checkout:async function(){var r=await H.post("/cart/checkout");return r.ok?{ok:true,order:r.data}:r}
 };
 A.wishlist={
  list:async function(){var r=await H.get("/wishlist");return r.ok?{ok:true,items:r.data.items.map(function(i){return{id:i.id,artworkId:i.artwork_id,artwork:toArtwork(i.artwork)}})}:r},
  add:async function(artworkId){var r=await H.post("/wishlist",{artwork_id:artworkId});return r.ok?{ok:true,id:r.data.item.id}:r},
  remove:async function(itemId){var r=await H.del("/wishlist/"+encodeURIComponent(itemId));return r.ok?{ok:true}:r}
 };
 A.follows={
  list:async function(){var r=await H.get("/follows");return r.ok?{ok:true,items:r.data.items.map(function(i){return{id:i.id,artistId:i.artist_id}})}:r},
  add:async function(artistId){var r=await H.post("/follows",{artist_id:artistId});return r.ok?{ok:true,id:r.data.item.id}:r},
  remove:async function(itemId){var r=await H.del("/follows/"+encodeURIComponent(itemId));return r.ok?{ok:true}:r}
 };
 A.notifications={
  unread:async function(){var r=await H.get("/me/notifications",{unread:"true",page_size:1});return r.ok?{ok:true,unread:r.data.unread_count}:r},
  list:async function(){var r=await H.get("/me/notifications",{page_size:50});return r.ok?{ok:true,items:r.data.items.map(function(n){return{id:n.id,message:n.message,read:n.read,at:n.created_at}}),unread:r.data.unread_count}:r},
  read:async function(id){var r=await H.put("/me/notifications/"+encodeURIComponent(id));return r.ok?{ok:true}:r},
  readAll:async function(){var r=await H.post("/me/notifications/read-all");return r.ok?{ok:true}:r}
 };
 A.password={
  change:async function(d){var bad=pwCheck(d.next,d.confirm,"next","confirm");if(bad)return bad;var r=await H.post("/auth/change-password",{current_password:d.current,new_password:d.next,confirm_password:d.confirm});return r.ok?{ok:true}:r},
  forgot:async function(email){var r=await H.post("/auth/forgot-password",{email:email});return r.ok?{ok:true,message:r.data.message}:r},
  resend:async function(email){var r=await H.post("/auth/resend-reset-code",{email:email});return r.ok?{ok:true,message:r.data.message}:r},
  verify:async function(email,code){var r=await H.post("/auth/verify-reset-code",{email:email,code:code});return r.ok?{ok:true,token:r.data.reset_token}:r},
  reset:async function(d){var bad=pwCheck(d.next,d.confirm,"next","confirm");if(bad)return bad;var r=await H.post("/auth/reset-password",{reset_token:d.token,new_password:d.next,confirm_password:d.confirm});return r.ok?{ok:true,message:r.data.message}:r}
 };


 A.orders={
  list:async function(scope){var r=await H.get("/orders",{scope:scope||"mine",page:1,page_size:50});return r.ok?page(r.data,function(x){return x}):r},
  get:async function(id){var r=await H.get("/orders/"+encodeURIComponent(id));return r.ok?{ok:true,order:r.data}:r},
  setStatus:async function(id,status){var r=await H.put("/orders/"+encodeURIComponent(id),{status:status});return r.ok?{ok:true,order:r.data}:r}
 };
 A.payments={
  get:async function(orderId){var r=await H.get("/orders/"+encodeURIComponent(orderId)+"/payment");return r.ok?{ok:true,payment:r.data}:r},
  submit:async function(orderId,d){var r=await H.post("/orders/"+encodeURIComponent(orderId)+"/payment",d);return r.ok?{ok:true,payment:r.data}:r},
  verify:async function(orderId,d){var r=await H.post("/orders/"+encodeURIComponent(orderId)+"/payment/verify",d);return r.ok?{ok:true,payment:r.data}:r}
 };
 A.promotions={
  list:async function(artistId){var q=artistId?{artist_id:artistId}:{};var r=await H.get("/promotions",q);return r.ok?{ok:true,items:r.data.items}:r},
  create:async function(d){var r=await H.post("/promotions",d);return r.ok?{ok:true,promotion:r.data}:r},
  history:async function(id){var r=await H.get("/artworks/"+encodeURIComponent(id)+"/price-history");return r.ok?{ok:true,items:r.data.items}:r}
 };
 A.commissions={
  listJobs:async function(scope){var q=scope?{scope:scope}:{};var r=await H.get("/commissions",q);return r.ok?{ok:true,items:r.data.items}:r},
  listings:async function(artistId){var r=await H.get("/commission-listings",artistId?{artist_id:artistId}:{});return r.ok?{ok:true,items:r.data.items}:r},
  createListing:async function(d){var r=await H.post("/commission-listings",d);return r.ok?{ok:true,listing:r.data}:r},
  get:async function(id){var r=await H.get("/commissions/"+encodeURIComponent(id));return r.ok?{ok:true,job:r.data}:r},
  create:async function(d){var r=await H.post("/commissions",d);return r.ok?{ok:true,job:r.data}:r},
  submitPayment:async function(id){var r=await H.post("/commissions/"+encodeURIComponent(id)+"/payment");return r.ok?{ok:true,job:r.data}:r},
  verifyPayment:async function(id){var r=await H.post("/commissions/"+encodeURIComponent(id)+"/verify-payment");return r.ok?{ok:true,job:r.data}:r},
  action:async function(id,action){var r=await H.post("/commissions/"+encodeURIComponent(id)+"/"+encodeURIComponent(action));return r.ok?{ok:true,job:r.data}:r}
 };
 A.dataAdmin={
  previewClear:async function(scopes,preserve){var r=await H.post("/admin/data/clear/preview",{scopes:scopes,preserve_admins:preserve});return r.ok?{ok:true,plan:r.data}:r},
  clear:async function(b){var r=await H.post("/admin/data/clear",b);return r.ok?{ok:true,result:r.data}:r},
  previewReset:async function(preserve){var r=await H.post("/admin/data/reset/preview",{preserve_admins:preserve});return r.ok?{ok:true,plan:r.data}:r},
  reset:async function(b){var r=await H.post("/admin/data/reset",b);return r.ok?{ok:true,result:r.data}:r}
 };
 A.reviews={
  list:async function(artworkId){var r=await H.get("/reviews",{artwork_id:artworkId,page_size:50});return r.ok?{ok:true,items:r.data.items.map(function(x){return{id:x.id,user:x.user_name,rating:x.rating,text:x.comment,artwork_id:x.artwork_id,artist_id:x.artist_id,status:x.status,artwork_rating:x.artwork_rating||x.rating,artist_rating:x.artist_rating||x.rating}})}:r},
  eligibility:async function(artworkId){var r=await H.get("/artworks/"+encodeURIComponent(artworkId)+"/review-eligibility");return r.ok?{ok:true,eligible:r.data.eligible,reason:r.data.reason}:r},
  create:async function(d){var r=await H.post("/reviews",{artwork_id:d.artworkId,rating:d.rating,artwork_rating:d.artworkRating||d.rating,artist_rating:d.artistRating||d.rating,comment:d.text});return r.ok?{ok:true}:r}
 };
 A.dashboard={summary:async function(){var r=await H.get("/dashboard");if(!r.ok)return r;var s=r.data;
  return{ok:true,users:s.total_users,artists:s.total_artists,artworks:s.total_artworks,pending:s.pending_artworks,orders:s.total_orders,sales:s.total_sales,reviews:s.total_reviews,paymentsPending:s.payments_pending,paymentsPaid:s.payments_paid,commissions:s.commissions,promotions:s.promotions,blacklisted:s.blacklisted_users,blockedIps:s.blocked_ips}}};
 A.users={
  list:async function(p){var r=await H.get("/users",{page:p||1,page_size:15});return r.ok?page(r.data):r},
  ban:async function(id){var r=await H.post("/users/"+encodeURIComponent(id)+"/ban");return r.ok?{ok:true}:r},
  unban:async function(id){var r=await H.post("/users/"+encodeURIComponent(id)+"/unban");return r.ok?{ok:true}:r}
 };
 A.logs={list:async function(p){var r=await H.get("/logs",{page:p||1,page_size:15});return r.ok?page(r.data):r}};
 A.moderation={
  blacklist:async function(){var r=await H.get("/admin/blacklist");return r.ok?{ok:true,items:r.data.items}:r},
  blacklistAdd:async function(d){var r=await H.post("/admin/blacklist",d);return r.ok?{ok:true,item:r.data}:r},
  blacklistRemove:async function(id){var r=await H.del("/admin/blacklist/"+encodeURIComponent(id));return r.ok?{ok:true}:r},
  ips:async function(){var r=await H.get("/admin/ip-blocks");return r.ok?{ok:true,items:r.data.items}:r},
  ipAdd:async function(d){var r=await H.post("/admin/ip-blocks",d);return r.ok?{ok:true,item:r.data}:r},
  ipRemove:async function(id){var r=await H.del("/admin/ip-blocks/"+encodeURIComponent(id));return r.ok?{ok:true}:r}
 };
 return A;
})();
