/* One renderer per page. Pages only talk to A4S.api (real backend or mock fallback) - never to Data/localStorage directly. */
(function(){
var $=function(s){return document.querySelector(s)},U=A4S.ui,qs=Router.param;
var api=function(){return A4S.api};
var k=function(n){return n>=1000?(n/1000).toFixed(1).replace(".0","")+"K":String(n)};
var opts=function(a,all){return (all?'<option value="">'+all+'</option>':'')+a.map(function(x){return '<option value="'+U.esc(x[0])+'">'+U.esc(x[1])+'</option>'}).join("")};
var need=function(r){if(!r.ok)throw new Error(r.error||"Request failed");return r};   /* page-level catch (app.js) shows the error */
var me=function(){return AuthService.getCurrentUser()};
var empty=function(h,p){return '<div class="wrap"><section><h2>'+h+'</h2><p class="mute" style="margin-bottom:14px">'+p+'</p><a class="btn" href="index.html">Back to Explore</a></section></div>'};
var firstError=function(r){return Object.values(r.errors||{})[0]||r.error};
/* the password rules shown under every "new password" field - generated from Validation.PASSWORD_RULES, so the list and the check can never disagree */
var pwRules=function(){return '<div class="mute small">Password must contain:<ul style="margin:4px 0 8px 18px">'+Validation.PASSWORD_RULES.map(function(r){return '<li>'+r.text+'</li>'}).join("")+'</ul></div>'};
/* demo credentials are shown only on a developer machine (never on a deployed site) */
var isDevHost=function(){return["localhost","127.0.0.1","[::1]"].indexOf(location.hostname)>=0};
var here=function(){return location.pathname.split("/").pop()+location.search};
/* private pages: a visitor who is not logged in sees this - nothing is created or stored for them */
var gate=function(title){return '<div class="wrap"><section><h2>'+U.esc(title)+'</h2><p class="mute" style="margin-bottom:14px">\u0e01\u0e23\u0e38\u0e13\u0e32\u0e40\u0e02\u0e49\u0e32\u0e2a\u0e39\u0e48\u0e23\u0e30\u0e1a\u0e1a\u0e01\u0e48\u0e2d\u0e19\u0e08\u0e36\u0e07\u0e2a\u0e32\u0e21\u0e32\u0e23\u0e16\u0e43\u0e0a\u0e49\u0e1f\u0e31\u0e07\u0e01\u0e4c\u0e0a\u0e31\u0e19\u0e19\u0e35\u0e49\u0e44\u0e14\u0e49</p><a class="btn" href="login.html?next='+encodeURIComponent(here())+'">Login</a> <a class="btn ghost" href="index.html">Keep browsing</a></section></div>'};
/* only same-site page names are accepted for ?next= (prevents open redirects) */
var safeNext=function(v){return typeof v==="string"&&/^[a-z]+\.html(\?[A-Za-z0-9=&_%.-]*)?$/.test(v)?v:null};
var when=function(iso){return String(iso||"").replace("T"," ").slice(0,16)};
A4S.pages={
home:async function(){
 var st={by:"artwork",q:"",cat:"",rating:"",max:"",sort:"",page:1,artist:qs("artist")||""},seq=0;
 var cats=need(await api().categories.list()).items,artists=need(await api().artists.list()).items;
 var feat=need(await api().artworks.search({sort:"rating",pageSize:6})).items.filter(function(w){return w.availability!=="Sold"});
 $("#app").innerHTML='<div class="wrap"><section><h1>Art worth collecting.</h1><p class="mute">Original illustration, 3D and game assets from independent artists.</p><div class="rail">'+feat.map(U.card).join("")+'</div></section>'
 +'<section id="results"><h2>Discover</h2><form class="search" id="sf"><div class="srow"><select name="by">'+opts([["artwork","Artwork"],["artist","Artist"],["tag","Tag"]])+'</select>'
 +'<input name="q" placeholder="Search by title, artist or tag" style="flex:1;min-width:180px"><button class="btn">Search</button></div>'
 +'<div class="srow"><select name="cat">'+opts(cats.map(function(c){return [c.id,c.name]}),"All categories")+'</select>'
 +'<select name="rating">'+opts([["4.5","4.5 and up"],["4.8","4.8 and up"]],"Any rating")+'</select>'
 +'<select name="max">'+opts([["500","Up to \u0e3f500"],["1000","Up to \u0e3f1,000"],["2000","Up to \u0e3f2,000"]],"Any price")+'</select>'
 +'<select name="sort">'+opts([["newest","Newest"],["priceAsc","Price: low to high"],["priceDesc","Price: high to low"],["rating","Top rated"]],"Sort: Featured")+'</select></div></form><div id="grid"></div></section>'
 +'<section id="promos"><h2>Featured Promotions</h2><div class="promos">'+A4S.promos.map(function(p,i){var c=A4S.pal[i+1];return '<a class="promo" href="index.html?artist='+p.q+'#results" style="background:linear-gradient(135deg,'+c[0]+','+c[1]+')"><b>'+p.big+'</b><span>'+U.esc(p.who)+'</span><small>'+p.txt+'</small><span class="btn sm ghost" style="color:#fff;border-color:#fff;align-self:flex-start;margin-top:10px">Explore</span></a>'}).join("")+'</div></section>'
 +'<section><h2>Artists of the Week</h2><div class="grid">'+artists.map(function(a){return '<a class="box" href="artist.html?id='+encodeURIComponent(a.id)+'"><div class="by">'+U.avatar(a)+U.esc(a.name)+'</div><p class="mute small">'+U.esc(a.headline)+'</p><p>'+U.stars(a.rating)+'</p></a>'}).join("")+'</div></section></div>';
 var f=$("#sf");
 async function draw(){
  var mine=++seq;   /* ignore answers that arrive after a newer search was started */
  var res=await api().artworks.search({query:st.q,type:st.by,filters:{category:st.cat,minRating:st.rating,maxPrice:st.max,artist:st.artist},sort:st.sort,page:st.page,pageSize:8});
  if(mine!==seq)return;
  if(!res.ok){$("#grid").innerHTML='<p class="err">'+U.esc(firstError(res))+'</p>';return}
  st.page=res.page;
  $("#grid").innerHTML=(res.total?'<p class="mute small" style="margin-bottom:12px">'+res.total+' artworks</p><div class="grid">'+res.items.map(U.card).join("")+'</div>':'<p class="mute">No artwork matches. Try clearing a filter.</p>')
  +(res.totalPages>1?'<div class="pager"><button class="btn ghost" data-pg="-1"'+(res.page<2?' disabled':'')+'>Previous</button><span>'+res.page+' / '+res.totalPages+'</span><button class="btn ghost" data-pg="1"'+(res.page>=res.totalPages?' disabled':'')+'>Next</button></div>':'');
 }
 function read(){var d=new FormData(f);["by","q","cat","rating","max","sort"].forEach(function(n){st[n]=d.get(n)});st.page=1;draw()}
 f.addEventListener("input",read);f.addEventListener("submit",function(e){e.preventDefault();read()});
 $("#grid").addEventListener("click",function(e){var b=e.target.closest("[data-pg]");if(b){st.page+=+b.dataset.pg;draw()}});
 await draw();
},
artwork:async function(){
 var r=await api().artworks.get(qs("id"));
 if(!r.ok){$("#app").innerHTML=empty("Artwork not found","It may have been removed or is not published yet.");return}
 var w=r.artwork,ar=await api().artists.get(w.artist),a=ar.ok?ar.artist:{id:w.artist,name:w.artistName};
 var ok=w.availability==="Available",dis=ok?"":" disabled",lim=w.type==="LIMITED",user=me();
 var more=(await api().artworks.search({filters:{artist:a.id},pageSize:5})).items.filter(function(x){return x.id!==w.id}).slice(0,4);
 var rv=await api().reviews.list(w.id),el=user?await api().reviews.eligibility(w.id):null;
 var reviews='<section id="reviews"><h2>Reviews</h2>'+(rv.items&&rv.items.length?rv.items.map(function(x){return '<div class="box" style="margin-bottom:10px"><b>'+U.esc(x.user)+'</b> <span class="mute">\u2605 '+x.rating+'</span><p>'+U.esc(x.text)+'</p></div>'}).join(""):'<p class="mute">No reviews yet.</p>')
 +(el&&el.ok&&el.eligible?'<form class="form" id="reviewForm" data-art="'+U.esc(w.id)+'" style="margin:18px 0 0"><select name="artworkRating">'+opts([["5","Artwork: 5 - Excellent"],["4","Artwork: 4 - Good"],["3","Artwork: 3 - Okay"],["2","Artwork: 2 - Poor"],["1","Artwork: 1 - Bad"]])+'</select><select name="artistRating">'+opts([["5","Artist: 5 - Excellent"],["4","Artist: 4 - Good"],["3","Artist: 3 - Okay"],["2","Artist: 2 - Poor"],["1","Artist: 1 - Bad"]])+'</select><input name="text" placeholder="Write your review (5+ characters)"><p class="err" id="revErr"></p><button class="btn">Post review</button></form>'
  :(user&&el&&el.ok?'<p class="mute small" style="margin-top:12px">'+U.esc(el.reason)+'</p>':''))+'</section>';
 $("#app").innerHTML='<div class="wrap"><section class="detail"><div class="thumb wm"><img alt="'+U.esc(w.title)+'" src="'+U.art(w.seed)+'"></div><div>'
 +'<h1>'+U.esc(w.title)+'</h1><a class="by" href="artist.html?id='+encodeURIComponent(a.id)+'">'+U.avatar(a)+U.esc(a.name)+'</a>'
 +'<p class="price">'+U.money(w.price)+'<small>'+U.stars(w.rating)+'</small></p>'
 +'<p><span class="pill '+U.cls(w.availability)+'">'+U.esc(w.availability)+'</span> <span class="pill">'+(lim?"LIMITED":"UNLIMITED LICENSE")+'</span> <span class="pill">'+U.esc(w.cat)+'</span></p>'
 +'<p>'+U.esc(w.desc)+'</p><p>'+w.tags.map(function(t){return '<span class="pill">#'+U.esc(t)+'</span> '}).join("")+'</p>'
 +'<div class="acts"><button class="btn" data-add="'+U.esc(w.id)+'"'+dis+'>Add to Cart</button><button class="btn ghost" data-buy="'+U.esc(w.id)+'"'+dis+'>Buy Now</button>'
 +'<button class="ib heart-btn'+(A4S.priv.isWishlisted(w.id)?' on':'')+'" style="border:1px solid var(--line);border-radius:50%" data-heart="'+U.esc(w.id)+'" aria-label="Wishlist">'+U.icon("heart")+'</button></div>'
 +'<p class="mute small">'+(lim?"Limited works are sold once and locked while a payment is pending.":"Unlimited licence: can be sold repeatedly. The original file is delivered after purchase.")+'</p></div></section>'
 +reviews+(more.length?'<section><h2>More from '+U.esc(a.name)+'</h2><div class="grid">'+more.map(U.card).join("")+'</div></section>':'')+'</div>';
},
artist:async function(){
 var id=qs("id"),a;
 if(id){var one=await api().artists.get(id);if(!one.ok){$("#app").innerHTML=empty("Artist not found","This artist does not exist.");return}a=one.artist}
 else{a=need(await api().artists.list()).items[0]}
 var fl=A4S.priv.isFollowing(a.id),works=need(await api().artworks.search({filters:{artist:a.id},pageSize:50})).items,user=me();
 var mine=user&&user.role==="ARTIST"&&user.id===a.id;
 $("#app").innerHTML='<div class="wrap"><section><div class="ph">'+U.avatar(a)+'<div><h1 style="margin:0">'+U.esc(a.name)+'</h1><p>'+U.esc(a.headline)+'</p><p>'+U.stars(a.rating)+' &nbsp; '+k(a.followers+(fl?1:0))+' followers</p></div></div>'
 +'<p style="max-width:560px;margin:18px 0">'+U.esc(a.bio)+'</p><button class="btn'+(fl?' ghost':'')+'" data-follow="'+U.esc(a.id)+'">'+(fl?"Following":"Follow")+'</button> '
 +(a.commission?'<a class="btn ghost" href="#commissions">Commission</a>':'<span class="pill">Commissions closed</span>')+'</section>'
 +' <section id="commissions"><h2>Commissions</h2>'+(a.commission?'<div class="tiers">'+(await api().commissions.listings(a.id)).items.map(function(t){return '<div class="box"><h2 style="margin-bottom:6px">'+U.esc(t.title)+'</h2><p>Starting at '+U.money(t.price)+'</p><p class="mute small">Delivery: '+t.days+' days · Revisions: '+t.revisions+'</p><p class="mute small">'+U.esc(t.description||'')+'</p><a class="btn ghost sm" href="commission.html?listing='+encodeURIComponent(t.id)+'">View Commission</a></div>'}).join('')+'</div>':'<p class="mute">This artist is not taking commissions right now.</p>')+'</section>'
 +'<section><h2>Artwork</h2><div class="grid">'+works.map(U.card).join("")+'</div></section><div id="manage"></div></div>';
 if(mine)await A4S.pages.manage();
},
manage:async function(){   /* artist's own CRUD panel: create / edit / submit for approval / delete */
 var list=need(await api().artworks.mine()).items,cats=need(await api().categories.list()).items;
 A4S.myWorks=list;
 var sales=await api().orders.list("sales"),salesItems=sales.ok?sales.items:[],revenue=salesItems.reduce(function(n,o){return n+Number(o.sales_total||0)},0);
 /* real preview when the backend has one; otherwise the generated placeholder (see the image error handler in app.js) */
  var thumb=function(w){var ph=U.art(w.seed);return A4S.mode==="api"?'<img class="thumb-sm" alt="" src="'+A4S.config.apiBase+'/artworks/'+encodeURIComponent(w.id)+'/preview" data-fallback="'+ph+'">':'<img class="thumb-sm" alt="" src="'+ph+'">'};
  var rows=list.map(function(w){var open=w.status==="DRAFT"||w.status==="REJECTED";
  return '<tr><td>'+thumb(w)+'</td><td>'+U.esc(w.title)+(w.rejectReason?'<div class="mute small">Rejected: '+U.esc(w.rejectReason)+'</div>':'')+'</td><td>'+U.money(w.price)+'</td><td><span class="pill '+U.cls(w.status)+'">'+U.esc(w.status)+'</span></td><td>'
  +(open?'<button class="btn ghost sm" data-art-edit="'+U.esc(w.id)+'">Edit</button> <button class="btn sm" data-art-submit="'+U.esc(w.id)+'">Submit</button> ':'')
  +'<button class="btn ghost sm" data-art-del="'+U.esc(w.id)+'">Delete</button></td></tr>'}).join("");
 var count=function(st){return list.filter(function(w){return w.status===st}).length};
  var stats='<section><h2>Dashboard</h2><div class="stats">'+[["Total artwork",list.length],["Pending approval",count("PENDING_APPROVAL")],["Approved",count("APPROVED")],["Sales revenue",U.money(revenue)]]
   .map(function(x){return '<div class="stat"><span class="mute">'+x[0]+'</span><b>'+(typeof x[1]==="number"?x[1].toLocaleString():x[1])+'</b></div>'}).join("")+'</div></section>';
  $("#manage").innerHTML=stats+'<section><h2>My Artwork</h2><div class="tw"><table><tr><th></th><th>Title</th><th>Price</th><th>Status</th><th></th></tr>'+(rows||'<tr><td colspan="5" class="mute">No artwork yet. Create your first piece below.</td></tr>')+'</table></div></section>'
 +'<section><h2 id="formTitle">New artwork</h2><form class="form" id="artForm" style="margin:0" novalidate><input type="hidden" name="artId">'
 +'<input name="title" placeholder="Title"><input name="price" type="number" step="0.01" min="0" placeholder="Price (THB)">'
 +'<select name="category">'+opts(cats.map(function(c){return [c.id,c.name]}))+'</select><select name="sale_type">'+opts([["UNLIMITED","UNLIMITED"],["LIMITED","LIMITED"]])+'</select>'
 +'<input name="tags" placeholder="tags, comma separated"><textarea name="description" rows="3" placeholder="Description"></textarea>'
 +'<label class="mute small" for="artFile">Artwork image: PNG, JPG or WebP, up to 3 MB (leave empty to keep the current one)</label><input type="file" id="artFile" name="file" accept="image/png,image/jpeg,image/webp">'
  +'<p class="err" id="artErr"></p><button class="btn">Save as draft</button></form></section>'
 +'<section><h2>Commission Listing</h2><form class="form" id="commissionListingForm" style="margin:0" novalidate><input name="title" placeholder="Commission title"><textarea name="description" rows="3" placeholder="Description"></textarea><textarea name="conditions" rows="2" placeholder="Conditions"></textarea><input name="price" type="number" min="0" step="0.01" placeholder="Starting price"><input name="days" type="number" min="1" max="365" value="7" placeholder="Days"><input name="revisions" type="number" min="0" max="20" value="1" placeholder="Revisions"><p class="err" id="commissionListingErr"></p><button class="btn">Create commission listing</button></form></section>'
 +'<section><h2>Promotion</h2><form class="form" id="promotionForm" style="margin:0" novalidate><input name="title" placeholder="Promotion title"><select name="type"><option value="PERCENTAGE">Percentage</option><option value="FIXED_AMOUNT">Fixed amount</option></select><input name="value" type="number" min="0" step="0.01" placeholder="Discount value"><input name="start_at" type="datetime-local"><input name="end_at" type="datetime-local"><input name="artwork_id" placeholder="Artwork ID"><p class="err" id="promotionErr"></p><button class="btn">Create promotion</button></form></section>';
},
wishlist:async function(){
 if(!me()){$("#app").innerHTML=gate("My Wishlist");return}
 var r=need(await api().wishlist.list());A4S.priv.setWishlist(r.items);
 var items=r.items.map(function(i){return i.artwork});
 $("#app").innerHTML='<div class="wrap"><section><h2>My Wishlist</h2>'+(items.length?'<div class="grid">'+items.map(U.card).join("")+'</div>':'<p class="mute" style="margin-bottom:14px">Tap the heart on any artwork to save it here.</p><a class="btn" href="index.html">Browse artwork</a>')+'</section></div>';
},
cart:async function(){
 if(!me()){$("#app").innerHTML=gate("Cart");return}
 var cart=need(await api().cart.get()).cart,list=cart.items;A4S.priv.setCart(cart);
 var blocked=list.some(function(i){return !i.purchasable});
 var rows=list.map(function(i){var w=i.artwork,q=i.quantity,id=U.esc(i.id);
  return '<div class="row"><img alt="" src="'+U.art(w.seed)+'"><div style="flex:1"><a class="t" href="artwork.html?id='+encodeURIComponent(w.id)+'">'+U.esc(w.title)+'</a><div class="mute small">'+U.esc(w.artistName)+', '+U.esc(w.type)+(i.purchasable?'':' &middot; <b>'+U.esc(w.availability)+'</b>')+'</div></div>'
  +(w.type==="UNLIMITED"?'<span><button class="btn ghost sm" data-qty="'+id+'" data-d="-1">-</button> '+q+' <button class="btn ghost sm" data-qty="'+id+'" data-d="1">+</button></span>':'<span class="mute small">Qty 1</span>')
  +'<b>'+U.money(i.lineTotal)+'</b><button class="ib" data-rm="'+id+'" aria-label="Remove">&#10005;</button></div>'}).join("");
 $("#app").innerHTML='<div class="wrap"><section><h2>Cart</h2>'+(list.length?rows+'<div class="sum"><div><span>Subtotal</span><span>'+U.money(cart.total)+'</span></div><div><b>Total</b><b>'+U.money(cart.total)+'</b></div><button class="btn" data-checkout="1"'+(blocked?' disabled':'')+'>Checkout</button>'+(blocked?'<p class="err">Remove unavailable items to check out.</p>':'')+'<p class="mute small">The server recalculates the price when the order is created.</p></div>':'<p class="mute" style="margin-bottom:14px">Your cart is empty.</p><a class="btn" href="index.html">Browse artwork</a>')+'</section></div>';
},
orders:async function(){
 if(!me()){$("#app").innerHTML=gate("Orders");return}
 var r=need(await api().orders.list("mine")),items=r.items||[],jobr=await api().commissions.listJobs(),jobs=jobr.ok?jobr.items:[];
 var renderPayment=function(o){
  if(!["PENDING_PAYMENT","PAYMENT_SUBMITTED"].includes(o.status))return "";
  return '<div class="box" style="margin-top:10px"><b>Payment</b><form class="form mini payForm" data-order="'+U.esc(o.id)+'" style="margin-top:10px"><select name="method"><option value="QR_PAYMENT">QR Payment</option><option value="BANK_TRANSFER">Bank Transfer</option><option value="COD">COD</option></select><input name="amount" type="number" step="0.01" min="0" value="'+U.esc(String(o.total))+'" placeholder="Amount"><input name="slip" maxlength="20" autocomplete="off" placeholder="Type &quot;slip&quot; to attach the slip (QR / Bank transfer)"><p class="err" id="payErr-'+U.esc(o.id)+'"></p><button class="btn sm">Submit payment</button></form><p class="mute small">Overpayment is not refunded unless caused by a system error.</p></div>';
 };
 var renderJob=function(j){
  var actions=[];
  if(j.state==="BRIEF"||j.state==="PAYMENT")actions.push('<button class="btn sm" data-commission-pay="'+U.esc(j.id)+'">Submit payment</button>');
  if(j.state==="DELIVERED")actions.push('<button class="btn sm" data-commission-action="'+U.esc(j.id)+'" data-action="COMPLETED">Confirm completion</button>');
  return '<div class="box" style="margin-bottom:10px"><div class="srow"><b>'+U.esc(j.title)+'</b><span class="pill">'+U.esc(j.state)+'</span></div><p class="mute small">Job '+U.esc(j.id)+' · '+U.money(j.price)+' · '+U.esc(String(j.duration_days))+' days</p><p>'+U.esc((j.brief&&j.brief.details)||'Structured commission brief')+'</p>'+(j.deadline_at?'<p class="small">Deadline: '+U.esc(when(j.deadline_at))+(j.deadline_passed?' · <b>Deadline passed</b>':'')+'</p>':'')+(actions.length?'<div class="srow">'+actions.join(' ')+'</div>':'')+'</div>';
 };
 $("#app").innerHTML='<div class="wrap"><section><h2>My Orders</h2>'+(items.length?items.map(function(o){return '<div class="box" style="margin-bottom:12px"><div class="srow"><b>Order '+U.esc(o.id)+'</b><span class="pill">'+U.esc(o.status)+'</span></div><p class="mute small">'+U.esc(String(o.created_at||"").slice(0,16))+' · Total '+U.money(o.total)+'</p><div>'+o.items.map(function(i){return '<span class="pill">'+U.esc(i.title)+' × '+i.quantity+'</span> '}).join('')+'</div>'+renderPayment(o)+'</div>'}).join(''):'<p class="mute">No orders yet.</p>')+'</section><section><h2>My Commissions</h2>'+(jobs.length?jobs.map(renderJob).join(''):'<p class="mute">No commission jobs yet.</p>')+'</section></div>';
},
commission:async function(){
 var listingId=qs("listing"),user=me();
 if(!listingId){$("#app").innerHTML=empty("Commission listing","Choose a commission listing from an artist profile.");return}
 var lr=await api().commissions.listings(),list=(lr.ok?lr.items:[]),listing=list.find(function(x){return x.id===listingId});
 if(!listing){$("#app").innerHTML=empty("Commission not found","This listing is no longer available.");return}
 $("#app").innerHTML='<div class="wrap"><section><h1>'+U.esc(listing.title)+'</h1><p>'+U.esc(listing.description)+'</p><div class="box"><p><b>'+U.money(listing.price)+'</b> · '+listing.days+' days · '+listing.revisions+' revisions</p><p class="mute small">'+U.esc(listing.conditions||"")+'</p></div>'+(user&&user.id!==listing.artist_id?'<h2 style="margin-top:22px">Commission brief</h2><form id="commissionForm" class="form" data-listing="'+U.esc(listing.id)+'" novalidate><input name="type" placeholder="Commission type"><textarea name="details" rows="4" placeholder="What should be created?"></textarea><input name="references" placeholder="Reference links (plain text)"><input name="size" placeholder="Size / resolution"><input name="style" placeholder="Style"><input name="background" placeholder="Background"><input name="character_count" type="number" min="1" value="1" placeholder="Character count"><textarea name="additional_requests" rows="3" placeholder="Additional requests"></textarea><p class="err" id="commissionErr"></p><button class="btn">Create commission request</button></form>':'<p class="mute" style="margin-top:18px">Login as a buyer to request this commission.</p>')+'</section></div>';
},
auth:function(mode){
 var reg=mode==="register",real=A4S.mode==="api";
 /* MOCK mode has no password authentication, so there is nothing to log in to (the page says so instead of showing a form that cannot work) */
 if(!real){$("#app").innerHTML='<div class="wrap"><section><h1>'+(reg?"Create account":"Welcome back")+'</h1><p class="mute" style="margin-bottom:14px">'+U.esc(AuthService.NEEDS_BACKEND)+'</p><a class="btn" href="index.html">Back to Explore</a></section></div>';return}
 $("#app").innerHTML='<div class="wrap"><section><form class="form" id="af" novalidate><h1>'+(reg?"Create account":"Welcome back")+'</h1>'
 +(reg?'<input name="name" placeholder="Display name" autocomplete="nickname">':'')
 +'<input name="email" type="email" placeholder="Email" autocomplete="email"><input name="password" type="password" placeholder="Password" autocomplete="'+(reg?'new-password':'current-password')+'">'
 +(reg?pwRules()+'<input name="confirm" type="password" placeholder="Confirm password" autocomplete="new-password">':'<p class="mute small"><a href="forgot.html"><u>Forgot password?</u></a></p>')
 +(reg?'<select name="role">'+opts([["USER","I want to buy art"],["ARTIST","I sell art"]])+'</select>':'')
 +'<p class="err" id="err"></p><button class="btn">'+(reg?"Create Account":"Login")+'</button>'
 +'<p class="mute small">'+(reg?'Have an account? <a href="login.html"><u>Login</u></a>':'New here? <a href="register.html"><u>Register</u></a>')+'. Passwords are hashed on the server.</p>'
 +(!reg&&isDevHost()?'<p class="mute small">Dev demo accounts: admin@art4sells.test, mika@art4sells.test (artist), buyer@art4sells.test. Password: Demo1234!</p>':'')+'</form></section></div>';
 $("#af").addEventListener("submit",async function(e){e.preventDefault();
  var d=Object.fromEntries(new FormData(e.target)),r=reg?await api().auth.register(d):await api().auth.login(d);
  if(!r.ok){$("#err").textContent=firstError(r);return}
  location.href=safeNext(qs("next"))||(r.user.role==="ADMIN"?"admin.html":"index.html")});
},
dmScopes:[["users","Users"],["artworks","Artworks"],["categories","Categories"],["orders","Orders"],["reviews","Reviews"],["cart","Cart"],["wishlist","Wishlist"],["follows","Follows"],["notifications","Notifications"],["audit_logs","Audit Logs"]],
dataManagement:function(){   /* admin only; the server enforces everything again (2-step confirmation, admin role, dependencies) */
 var boxes=A4S.pages.dmScopes.map(function(s){return '<label class="chk"><input type="checkbox" name="scope" value="'+U.esc(s[0])+'"> '+U.esc(s[1])+'</label>'}).join("");
 return '<div class="box"><h3>Clear Data</h3><p class="mute small">Choose what to delete. Related data is cleared together so nothing is left pointing at missing records.</p>'
  +'<form id="dmForm">'+boxes+'<label class="chk"><input type="checkbox" name="preserve" checked> Preserve Admin Accounts</label>'
  +'<label class="chk"><input type="checkbox" checked disabled> Preserve System Configuration</label><button class="btn danger">Review &amp; continue</button></form></div>'
  +'<div id="dmStep"></div>'
  +'<div class="box"><h3>Reset Demo Data</h3><p class="mute small">Replace all data with the demo dataset. Audit logs are kept.</p><button class="btn ghost" data-dm-reset-preview="1">Review reset</button></div>';
},
dmPanel:function(plan,kind){   /* step 1 summary -> step 2 typed confirmation */
 var counts=plan.counts||plan.current_counts||{},rows=Object.keys(counts).map(function(k){return '<tr><td>'+U.esc(k)+'</td><td>'+U.esc(counts[k])+'</td></tr>'}).join("");
 var auto=plan.auto_included&&plan.auto_included.length?'<p class="small">Also cleared because they depend on your selection: <b>'+U.esc(plan.auto_included.join(", "))+'</b></p>':'';
 var word=kind==="clear"?"CLEAR":"RESET";
 return '<div class="box warn" id="dmSummary"><h3>\u26a0\ufe0f '+(kind==="clear"?"Clear Database":"Reset Demo Data")+'</h3><p>This cannot be undone.</p>'
  +'<div class="tw"><table><tr><th>Data</th><th>'+(kind==="clear"?"To delete":"Now")+'</th></tr>'+rows+'</table></div>'+auto
  +'<p class="small">Admin accounts preserved: <b>'+(plan.preserve_admins?"yes":"no (your own account is still kept)")+'</b></p>'
  +'<div class="srow"><button class="btn ghost" data-dm-cancel="1">Cancel</button><button class="btn danger" data-dm-continue="1">Continue</button></div></div>'
  +'<div class="box warn" id="dmConfirm" hidden><form id="dmConfirmForm" data-kind="'+kind+'"><label>Type <b>'+word+'</b> to confirm</label><input name="text" autocomplete="off">'
  +(plan.requires_audit_confirmation?'<label>Audit logs will be deleted. Type <b>CLEAR AUDIT LOGS</b></label><input name="audit" autocomplete="off">':'')
  +'<p class="err" id="dmErr"></p><button class="btn danger">Confirm</button></form></div>';
},
forgot:function(){   /* Forgot Password: email -> 5-digit code -> new password (the reset token lives only in this closure) */
 var state={email:"",token:""},root=$("#app");
 var shell=function(inner){root.innerHTML='<div class="wrap"><section><div class="form" style="margin:0 auto">'+inner+'</div></section></div>'};
 var step1=function(note){shell('<h1>Forgot password</h1><p class="mute small">Enter your registered email. We will send a 5-digit verification code.</p><form id="f1" novalidate><input name="email" type="email" placeholder="Email" autocomplete="email"><p class="err" id="e1"></p>'+(note?'<p class="small">'+U.esc(note)+'</p>':'')+'<button class="btn">Send code</button></form><p class="mute small"><a href="login.html"><u>Back to login</u></a></p>');
  $("#f1").addEventListener("submit",async function(e){e.preventDefault();var email=new FormData(e.target).get("email"),r=await api().password.forgot(email);
   if(!r.ok){$("#e1").textContent=firstError(r);return}state.email=email;step2(r.message)})};
 var step2=function(note){shell('<h1>Enter code</h1><p class="small">'+U.esc(note)+'</p><p class="mute small">The code is valid for 10 minutes.</p><form id="f2" novalidate><input name="code" inputmode="numeric" maxlength="5" placeholder="5-digit code" autocomplete="one-time-code"><p class="err" id="e2"></p><button class="btn">Verify</button></form><p class="mute small"><a href="#" id="resend"><u>Send a new code</u></a></p>');
  $("#f2").addEventListener("submit",async function(e){e.preventDefault();var r=await api().password.verify(state.email,new FormData(e.target).get("code"));
   if(!r.ok){$("#e2").textContent=firstError(r);return}state.token=r.token;step3()});
  $("#resend").addEventListener("click",async function(e){e.preventDefault();var r=await api().password.resend(state.email);$("#e2").textContent=r.ok?r.message:firstError(r)})};
 var step3=function(){shell('<h1>New password</h1><form id="f3" novalidate><input name="next" type="password" placeholder="New password" autocomplete="new-password"><input name="confirm" type="password" placeholder="Confirm new password" autocomplete="new-password">'+pwRules()+'<p class="err" id="e3"></p><button class="btn">Reset password</button></form>');
  $("#f3").addEventListener("submit",async function(e){e.preventDefault();var d=Object.fromEntries(new FormData(e.target));d.token=state.token;var r=await api().password.reset(d);
   if(!r.ok){$("#e3").textContent=firstError(r);if(r.code==="INVALID_RESET"){state.token="";step1()}return}
   state.token="";shell('<h1>Password updated</h1><p>'+U.esc(r.message)+'</p><a class="btn" href="login.html">Login</a>')})};
 if(A4S.mode!=="api"){shell('<h1>Forgot password</h1><p class="mute">Password recovery needs the real backend. It is not available in MOCK mode.</p><a class="btn" href="index.html">Back</a>');return}
 step1();
},
settings:async function(){
 var usr=me();
 if(!usr){$("#app").innerHTML=gate("Settings");return}
 var info=await api().auth.me(),again=info.passwordChangeAvailableAt?new Date(info.passwordChangeAvailableAt):null;
 var note=again?'You can change your password again on <b>'+U.esc(again.getUTCDate()+" "+again.toLocaleString("en-US",{month:"long",timeZone:"UTC"})+" "+again.getUTCFullYear())+'</b>.':'You can change your password now.';
 $("#app").innerHTML='<div class="wrap"><section><h2>Account</h2><div class="box"><p><b>'+U.esc(usr.name)+'</b></p><p class="mute">'+U.esc(usr.email)+' &middot; '+U.esc(usr.role)+'</p></div></section>'
  +'<section><h2>Security: Change password</h2><form class="form" id="pwForm" style="margin:0" novalidate>'
  +'<input name="current" type="password" placeholder="Current password" autocomplete="current-password"><input name="next" type="password" placeholder="New password" autocomplete="new-password"><input name="confirm" type="password" placeholder="Confirm new password" autocomplete="new-password">'
  +pwRules()+'<p class="mute small">'+note+'</p><p class="err" id="pwErr"></p><button class="btn">Change password</button></form></section></div>';
},
notifications:async function(){
 if(!me()){$("#app").innerHTML=gate("Notifications");return}
 var r=need(await api().notifications.list());A4S.priv.unread=r.unread;A4S.refresh();
 $("#app").innerHTML='<div class="wrap"><section><h2>Notifications</h2>'+(r.items.length?'<button class="btn ghost sm" data-notif-all="1" style="margin-bottom:12px">Mark all as read</button>'
  +r.items.map(function(n){return '<div class="box" style="margin-bottom:10px">'+(n.read?'':'<span class="pill">New</span> ')+U.esc(n.message)+'<div class="mute small">'+U.esc(when(n.at))+'</div>'+(n.read?'':'<button class="btn ghost sm" data-notif="'+U.esc(n.id)+'">Mark as read</button>')+'</div>'}).join("")
  :'<p class="mute">No notifications yet.</p>')+'</section></div>';
},
login:function(){return A4S.pages.auth("login")},
register:function(){return A4S.pages.auth("register")},
admin:async function(){
 var usr=me();
 if(!usr||usr.role!=="ADMIN"){$("#app").innerHTML='<div class="wrap"><section><h2>Admins only</h2><p class="mute" style="margin-bottom:14px">Log in with an ADMIN account to open the dashboard.</p><a class="btn" href="login.html?next='+encodeURIComponent(here())+'">Login</a></section></div>';return}
 var tabs=["Dashboard","Users","Artwork Approval","Audit Logs","Data Management","Reviews","Reports","Payments","Commissions","Blacklist","IP Block"].concat(A4S.devTools?["Dev Mailbox"]:[]),pg=Math.max(1,parseInt(qs("page"),10)||1),body;
 var tab=tabs.indexOf(qs("tab"))>-1?qs("tab"):"Dashboard";   /* allowlist: text from the URL is never printed into the page */
 var pager=function(r,t){return r.totalPages>1?'<div class="pager"><a class="btn ghost" href="admin.html?tab='+encodeURIComponent(t)+'&page='+Math.max(1,r.page-1)+'">Previous</a><span>'+r.page+' / '+r.totalPages+'</span><a class="btn ghost" href="admin.html?tab='+encodeURIComponent(t)+'&page='+Math.min(r.totalPages,r.page+1)+'">Next</a></div>':''};
 if(tab==="Dashboard"){
  var S=need(await api().dashboard.summary());
  body='<div class="stats">'+[["Total Users",S.users],["Total Artists",S.artists],["Total Artworks",S.artworks],["Pending Approval",S.pending],["Total Orders",S.orders],["Total Sales",U.money(S.sales)],["Total Reviews",S.reviews]]
   .map(function(x){return '<div class="stat"><span class="mute">'+x[0]+'</span><b>'+(typeof x[1]==="number"?x[1].toLocaleString():x[1])+'</b></div>'}).join("")+'</div>';
 }else if(tab==="Artwork Approval"){
  var P=need(await api().artworks.submissions()).items;
  body='<div class="tw"><table><tr><th>Artwork</th><th>Artist</th><th>Submitted</th><th>Status</th><th></th></tr>'+P.map(function(p){return '<tr><td>'+U.esc(p.title)+'</td><td>'+U.esc(p.artistName)+'</td><td>'+U.esc(String(p.submittedAt||"").slice(0,10))+'</td><td><span class="pill '+U.cls(p.status)+'">'+U.esc(p.status)+'</span></td><td>'+(p.status==="PENDING_APPROVAL"?'<button class="btn sm" data-decide="'+U.esc(p.id)+'" data-v="approve">Approve</button> <button class="btn ghost sm" data-decide="'+U.esc(p.id)+'" data-v="reject">Reject</button>':"")+'</td></tr>'}).join("")+'</table></div>';
 }else if(tab==="Users"){
  var L=need(await api().users.list(pg));
  body='<div class="tw"><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr>'+L.items.map(function(u){return '<tr><td>'+U.esc(u.name)+'</td><td>'+U.esc(u.email)+'</td><td>'+U.esc(u.role)+'</td><td>'+U.esc(u.status)+'</td><td>'
   +(u.role==="ADMIN"?'':'<button class="btn ghost sm" data-ban="'+U.esc(u.id)+'" data-v="'+(u.status==="BANNED"?"unban":"ban")+'">'+(u.status==="BANNED"?"Unban":"Ban")+'</button>')+'</td></tr>'}).join("")+'</table></div>'+pager(L,"Users");
 }else if(tab==="Audit Logs"){
  var G=need(await api().logs.list(pg));
  body='<div class="tw"><table><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Result</th></tr>'+G.items.map(function(e){return '<tr><td>'+U.esc(String(e.timestamp).replace("T"," ").slice(0,19))+'</td><td>'+U.esc(e.actor_id)+'</td><td>'+U.esc(e.action)+'</td><td>'+U.esc(e.target_type+":"+e.target_id)+'</td><td>'+U.esc(e.result||"SUCCESS")+'</td></tr>'}).join("")+'</table></div>'+pager(G,"Audit Logs");
 }else if(tab==="Reviews"){
  var RV=need(await api().reviews.list(null));
  body='<div class="tw"><table><tr><th>User</th><th>Artwork</th><th>Rating</th><th>Status</th></tr>'+RV.items.map(function(x){return '<tr><td>'+U.esc(x.user)+'</td><td>'+U.esc(x.artwork_id||"")+'</td><td>'+U.esc(String(x.rating))+'</td><td>'+U.esc(x.status||"PUBLISHED")+'</td></tr>'}).join("")+'</table></div>';
 }else if(tab==="Reports"){
  var R=need(await api().dashboard.summary());
  body='<div class="stats">'+[["Pending payments",R.paymentsPending],["Paid payments",R.paymentsPaid],["Commissions",R.commissions],["Promotions",R.promotions],["Blacklisted users",R.blacklisted],["Blocked IPs",R.blockedIps]].map(function(x){return '<div class="stat"><span class="mute">'+x[0]+'</span><b>'+x[1]+'</b></div>'}).join("")+'</div><div class="box"><p class="mute small">Commission states</p><pre>'+U.esc(JSON.stringify(R, null, 2))+'</pre></div>';
 }else if(tab==="Payments"){
  var OR=need(await api().orders.list("all")),pending=OR.items.filter(function(o){return ["PAYMENT_SUBMITTED","PENDING_PAYMENT"].includes(o.status)}),ps=[];
  for(var oi=0;oi<pending.length;oi++){var pr=await api().payments.get(pending[oi].id);if(pr.ok)ps.push({order:pending[oi],payment:pr.payment})}
  body='<div class="tw"><table><tr><th>Order</th><th>Buyer</th><th>Method</th><th>Expected</th><th>Submitted</th><th>Status</th><th></th></tr>'+ps.map(function(x){return '<tr><td>'+U.esc(x.order.id)+'</td><td>'+U.esc(x.order.user_name||x.payment.user_id)+'</td><td>'+U.esc(x.payment.method||'-')+'</td><td>'+U.money(x.payment.expected_amount)+'</td><td>'+U.money(x.payment.submitted_amount||0)+'</td><td>'+U.esc(x.payment.status)+'</td><td>'+(x.payment.status==="PENDING_VERIFICATION"?'<button class="btn sm" data-pay-verify="'+U.esc(x.order.id)+'">Verify</button>':'')+'</td></tr>'}).join('')+'</table></div>'+(ps.length?'':'<p class="mute">No pending payments.</p>');
 }else if(tab==="Commissions"){
  var CJ=need(await api().commissions.listJobs("all"));
  body='<div class="tw"><table><tr><th>Job</th><th>Title</th><th>State</th><th>Payment</th><th>Deadline</th><th></th></tr>'+CJ.items.map(function(j){var a=[];if(j.state==="PAYMENT"&&j.payment_status==="PENDING_VERIFICATION")a.push('<button class="btn sm" data-commission-verify="'+U.esc(j.id)+'">Verify payment</button>');if(j.state==="ACCEPTED")a.push('<button class="btn sm" data-commission-action="'+U.esc(j.id)+'" data-action="IN_PROGRESS">Start work</button>');if(j.state==="IN_PROGRESS")a.push('<button class="btn sm" data-commission-action="'+U.esc(j.id)+'" data-action="DELIVERED">Mark delivered</button>');if(j.state==="DELIVERED")a.push('<span class="mute small">Awaiting buyer</span>');return '<tr><td>'+U.esc(j.id)+'</td><td>'+U.esc(j.title)+'</td><td>'+U.esc(j.state)+'</td><td>'+U.esc(j.payment_status)+'</td><td>'+U.esc(j.deadline_at?when(j.deadline_at):'-')+'</td><td>'+a.join(' ')+'</td></tr>'}).join('')+'</table></div>'+(CJ.items.length?'':'<p class="mute">No commission jobs.</p>');
 }else if(tab==="Blacklist"){
  var BL=need(await api().moderation.blacklist());
  body='<div class="box"><form class="form mini" id="blacklistForm"><input name="user_id" placeholder="User ID"><input name="reason" placeholder="Reason"><button class="btn sm">Blacklist user</button><p class="err" id="blackErr"></p></form></div><div class="tw"><table><tr><th>User</th><th>Reason</th><th></th></tr>'+BL.items.map(function(x){return '<tr><td>'+U.esc(x.user_name||x.user_id)+'</td><td>'+U.esc(x.reason)+'</td><td><button class="btn ghost sm" data-black-remove="'+U.esc(x.id)+'">Remove</button></td></tr>'}).join("")+'</table></div>';
 }else if(tab==="IP Block"){
  var IP=need(await api().moderation.ips());
  body='<div class="box"><form class="form mini" id="ipBlockForm"><input name="ip" placeholder="IP address"><input name="reason" placeholder="Reason"><button class="btn sm">Block IP</button><p class="err" id="ipErr"></p></form></div><div class="tw"><table><tr><th>IP</th><th>Reason</th><th></th></tr>'+IP.items.map(function(x){return '<tr><td>'+U.esc(x.ip)+'</td><td>'+U.esc(x.reason)+'</td><td><button class="btn ghost sm" data-ip-remove="'+U.esc(x.id)+'">Remove</button></td></tr>'}).join("")+'</table></div>';
 }else if(tab==="Dev Mailbox"){   /* DEVELOPMENT ONLY: shown only when the server reports A4S_DEV_TOOLS=true; the server checks ADMIN again */
  var M=need(await api().devTools.mailbox());
  body='<div class="box warn"><p class="small">'+U.esc(M.warning)+'</p></div><div class="tw"><table><tr><th>Recipient</th><th>Created</th><th>Expires</th><th>OTP</th><th>Purpose</th></tr>'
   +M.items.map(function(m){return '<tr><td>'+U.esc(m.recipient)+'</td><td>'+U.esc(String(m.created_at).replace("T"," ").slice(0,19))+'</td><td>'+U.esc(String(m.expires_at).replace("T"," ").slice(0,19))+'</td><td><b>'+U.esc(m.otp)+'</b>'+(m.expired?' <span class="mute small">(expired)</span>':'')+'</td><td>'+U.esc(m.purpose)+'</td></tr>'}).join("")
   +(M.items.length?'':'<tr><td colspan="5" class="mute">No messages yet.</td></tr>')+'</table></div>';
 }else if(tab==="Data Management"){
  body=A4S.pages.dataManagement();
 }else body='<div class="box"><p class="mute">'+U.esc(tab)+' is planned for a later phase.</p></div>';
 $("#app").innerHTML='<div class="wrap"><section class="adm"><nav class="side">'+tabs.map(function(t){return '<a class="'+(t===tab?"on":"")+'" href="admin.html?tab='+encodeURIComponent(t)+'">'+t+'</a>'}).join("")+'</nav><div><h2>'+tab+'</h2>'+body+'</div></section></div>';
}
};
})();
