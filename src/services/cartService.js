/* The "can this be bought?" rule lives here and in OrderService, not in button visibility. */
var CartService=(()=>{
 const S={},get=()=>AppState.get("cart",{});
 S.getCart=get;
 S.count=()=>Object.values(get()).reduce((s,q)=>s+q,0);
 S.addToCart=id=>{
  const w=ArtworkService.getArtwork(id);
  if(!w)return Result.fail("Artwork not found");
  if(w.availability==="Sold")return Result.fail("This artwork is already sold");
  if(w.availability==="Processing")return Result.fail("Another buyer has a payment pending for this artwork");
  const c=get();c[id]=w.type==="LIMITED"?1:(c[id]||0)+1;AppState.set("cart",c);return Result.ok({});
 };
 S.setQuantity=(id,q)=>{const c=get();if(q>0)c[id]=q;else delete c[id];AppState.set("cart",c)};
 S.removeFromCart=id=>S.setQuantity(id,0);
 S.clearCart=()=>AppState.set("cart",{});
 S.calculateSubtotal=()=>{const c=get();return Object.keys(c).reduce((s,id)=>{const w=ArtworkService.getArtwork(id);return s+(w?w.price*c[id]:0)},0)};
 return S;
})();
