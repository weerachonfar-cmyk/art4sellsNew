/* A4S.priv = the CURRENT user's private data (cart, wishlist, follows, unread notifications).
   - Lives in memory only: never written to localStorage / sessionStorage.
   - The backend is the source of truth; this is just a copy used to draw the page.
   - Cleared on logout, on a 401, and whenever the signed-in user changes, so one user's data can never show for another. */
A4S.priv=(function(){
 var P={userId:null,cart:{items:[],count:0,total:0},wish:{},follow:{},unread:0};
 var empty=function(){return{items:[],count:0,total:0}};
 P.clear=function(){P.userId=null;P.cart=empty();P.wish={};P.follow={};P.unread=0};
 P.load=async function(){
  var u=AuthService.getCurrentUser();
  if(!u){P.clear();return}
  if(P.userId&&P.userId!==u.id)P.clear();
  P.userId=u.id;
  var r=await Promise.all([A4S.api.cart.get(),A4S.api.wishlist.list(),A4S.api.follows.list(),A4S.api.notifications.unread()]);
  if(AuthService.getCurrentUser()===null||AuthService.getCurrentUser().id!==P.userId){P.clear();return}   /* session ended while loading */
  if(r[0].ok)P.setCart(r[0].cart);
  if(r[1].ok)P.setWishlist(r[1].items);
  if(r[2].ok)P.setFollows(r[2].items);
  if(r[3].ok)P.unread=r[3].unread;
 };
 P.setCart=function(cart){P.cart=cart};
 P.setWishlist=function(items){P.wish={};items.forEach(function(i){P.wish[i.artworkId]=i.id})};
 P.setFollows=function(items){P.follow={};items.forEach(function(i){P.follow[i.artistId]=i.id})};
 P.cartCount=function(){return P.cart.count};
 P.wishCount=function(){return Object.keys(P.wish).length};
 P.isWishlisted=function(artworkId){return Object.prototype.hasOwnProperty.call(P.wish,artworkId)};
 P.isFollowing=function(artistId){return Object.prototype.hasOwnProperty.call(P.follow,artistId)};
 P.cartItem=function(itemId){return P.cart.items.find(function(i){return i.id===itemId})};
 return P;
})();
