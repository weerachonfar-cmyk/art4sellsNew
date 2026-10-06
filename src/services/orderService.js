/* Order lifecycle. A LIMITED artwork is locked while any order for it is active; expiry/cancel unlocks it. */
var OrderService=(()=>{
 const S={};
 S.expireStale=()=>Data.find("orders",o=>o.status==="PENDING_PAYMENT"&&Date.parse(o.expiresAt)<Date.now()).forEach(o=>S.advance(o.id,"EXPIRED",null));
 S.hasActiveOrderFor=aid=>{S.expireStale();return Data.find("orders",o=>Const.ACTIVE_ORDER.includes(o.status)&&o.items.some(i=>i.artworkId===aid)).length>0};
 S.advance=(id,next,actor)=>{
  const o=Data.get("orders",id);if(!o)return Result.fail("Order not found");
  const t=StateMachine.transition(o.status,next,Const.ORDER);if(!t.ok)return t;
  if(next==="PAID")o.items.forEach(i=>ArtworkService.markSold(i.artworkId));
  AuditLog.add({actorId:actor?actor.id:"system",action:"ORDER_"+next,targetType:"order",targetId:id});
  return Result.ok({order:Data.update("orders",id,{status:next})});
 };
 S.createOrder=(user,cart)=>{
  const g=RBAC.check(user,"order.create");if(g)return g;
  const ids=Object.keys(cart||{});if(!ids.length)return Result.fail("Cart is empty");
  const items=[];
  for(const id of ids){const w=ArtworkService.getArtwork(id);
   if(!w||w.availability!=="Available")return Result.fail((w?w.title:"An artwork")+" is no longer available");
   items.push({artworkId:id,qty:cart[id],price:w.price})}
  const o=Data.insert("orders",{userId:user.id,items,total:items.reduce((s,i)=>s+i.price*i.qty,0),status:"CREATED",createdAt:new Date().toISOString(),expiresAt:new Date(Date.now()+Const.ORDER_TTL_MS).toISOString()});
  AuditLog.add({actorId:user.id,action:"ORDER_CREATED",targetType:"order",targetId:o.id});
  return S.advance(o.id,"PENDING_PAYMENT",user);
 };
 S.getOrder=id=>Data.get("orders",id);
 S.getUserOrders=uid=>Data.find("orders",o=>o.userId===uid);
 S.cancelOrder=(id,actor)=>{const o=S.getOrder(id);return o&&actor&&o.userId===actor.id?S.advance(id,"CANCELLED",actor):Result.fail("Cannot cancel this order")};
 S.expireOrder=id=>S.advance(id,"EXPIRED",null);
 S.hasPurchased=(uid,aid)=>Data.find("orders",o=>o.userId===uid&&o.status==="COMPLETED"&&o.items.some(i=>i.artworkId===aid)).length>0;
 return S;
})();
