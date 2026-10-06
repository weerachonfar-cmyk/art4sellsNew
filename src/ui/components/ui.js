/* Shared UI helpers and components. */
A4S.ui={
 esc:function(s){return String(s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})},
 money:function(n){return "\u0e3f"+n.toLocaleString("en-US")},
 stars:function(r){return r>0?"\u2605 "+r.toFixed(1):"New"},
 icon:function(n){var p={heart:"M12 20.5s-8.5-5-8.5-11A4.8 4.8 0 0 1 12 6.8a4.8 4.8 0 0 1 8.5 2.7c0 6-8.500 11-8.500 11z",bag:"M5 8h14l-1 12H6zM9 8a3 3 0 0 1 6 0",user:"M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.500-6 8-6s8 2 8 6",menu:"M4 7h16M4 12h16M4 17h10"};return '<svg viewBox="0 0 24 24"><path d="'+p[n]+'"/></svg>'},
 art:function(seed){ /* generated placeholder artwork; Phase 3: serve watermarked preview files */
  var c=A4S.pal[seed%A4S.pal.length],r=function(n){return (seed*37+n*91)%100};
  var s='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="'+c[0]+'"/><stop offset="1" stop-color="'+c[1]+'"/></linearGradient></defs><rect width="400" height="500" fill="url(#g)"/>';
  for(var i=0;i<4;i++)s+='<circle cx="'+r(i)*4+'" cy="'+(100+r(i+5)*3.5)+'" r="'+(40+r(i+9))+'" fill="'+c[2]+'" opacity="'+(0.25+i*0.12)+'"/>';
  s+='<path d="M0 '+(380+r(3)/2)+' Q120 '+(300+r(4))+' 240 '+(400-r(5)/2)+' T400 '+(340+r(6))+' V500 H0Z" fill="'+c[0]+'" opacity=".75"/></svg>';
  return "data:image/svg+xml,"+encodeURIComponent(s);
 },
 avatar:function(a,big){var i=parseInt(String(a.id).slice(1),10);return '<span class="av" style="background:'+A4S.pal[(i||0)%A4S.pal.length][0]+'">'+A4S.ui.esc(String(a.name).charAt(0))+'</span>'},
 cls:function(s){return String(s).replace(/[^A-Za-z0-9_-]/g,"")},
 card:function(w){
  var u=A4S.ui,a={id:w.artist,name:w.artistName||"Artist"},on=A4S.priv.isWishlisted(w.id),h="artwork.html?id="+encodeURIComponent(w.id);
  return '<article class="card"><a href="'+h+'"><div class="thumb wm"><img loading="lazy" alt="'+u.esc(w.title)+'" src="'+u.art(w.seed)+'"></div></a>'
  +'<button class="ib heart'+(on?' on':'')+'" data-heart="'+u.esc(w.id)+'" aria-label="Wishlist">'+u.icon("heart")+'</button>'
  +'<div class="meta"><a class="t" href="'+h+'">'+u.esc(w.title)+'</a><a class="by" href="artist.html?id='+encodeURIComponent(a.id)+'">'+u.avatar(a)+u.esc(a.name)+'</a>'
  +'<div class="sub"><span class="mute">'+u.esc(w.cat)+'</span><span>'+u.stars(w.rating)+'</span></div><b>'+(w.currentPrice!==undefined&&w.currentPrice<w.price?'<s class="mute small">'+u.money(w.price)+'</s> ':'')+u.money(w.currentPrice===undefined?w.price:w.currentPrice)+'</b></div></article>';
 },
 header:function(){
  var u=A4S.ui,usr=AuthService.getCurrentUser(),n=A4S.priv.cartCount(),w=A4S.priv.wishCount(),unread=A4S.priv.unread;
  var links=[["index.html","Explore"],["index.html#promos","Promotions"],["artist.html?id=a1","Artists"],["artist.html?id=a1#commissions","Commissions"]];
  if(usr)links.push(["orders.html","Orders"]);
  if(usr&&usr.role==="ARTIST")links.push(["artist.html?id="+encodeURIComponent(usr.id)+"#manage","My Artwork"]);
  if(usr&&usr.role==="ADMIN")links.push(["admin.html","Admin"]);
  return '<header><div class="wrap bar"><div><button class="ib" id="menuBtn" aria-label="Menu">'+u.icon("menu")+'</button></div>'
  +'<a class="logo" href="index.html">Art 4 Sells</a><div class="icons">'
  +'<a class="ib" href="cart.html" aria-label="Cart">'+u.icon("bag")+(n?'<i class="badge">'+n+'</i>':'')+'</a>'
  +'<a class="ib" href="wishlist.html" aria-label="Wishlist">'+u.icon("heart")+(w?'<i class="badge">'+w+'</i>':'')+'</a>'
  +'<a class="ib" href="'+(usr?'#':'login.html')+'" id="profile" aria-label="Profile">'+u.icon("user")+'</a></div></div>'
  +'<nav class="menu" id="menu">'+links.map(function(l){return '<a href="'+l[0]+'">'+l[1]+'</a>'}).join("")
  +(usr?'<a href="notifications.html">Notifications'+(unread?' ('+unread+')':'')+'</a><a href="settings.html">Settings</a><a href="#" id="logout">Log out ('+u.esc(usr.name)+', '+u.esc(usr.role)+')</a>':'<a href="login.html">Login</a><a href="register.html">Register</a>')+'</nav>'+(A4S.mode==="mock"?'<div class="banner">MOCK MODE: the backend is not connected. Data shown is demo data stored in this browser only.</div>':'')+'</header>';
 },
 fail:function(msg){return '<div class="wrap"><section><h2>Something went wrong</h2><p class="mute" style="margin-bottom:14px">'+A4S.ui.esc(msg)+'</p><a class="btn" href="">Try again</a></section></div>'},
 toast:function(m){var d=document.createElement("div");d.className="toast";d.textContent=m;document.body.appendChild(d);setTimeout(function(){d.remove()},1800)}
};
