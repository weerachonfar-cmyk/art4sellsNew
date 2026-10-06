/* Domain model only (Phase 4 adds UI/payment). Every status change goes through StateMachine. */
var CommissionService=(()=>{
 const S={};
 S.createCommissionListing=(artist,d)=>{
  const g=RBAC.check(artist,"commission.manage");if(g)return g;
  const e={};if(Validation.validateRequired(d.title,"Title"))e.title="Title is required";if(Validation.validatePrice(d.price))e.price=Validation.validatePrice(d.price);
  if(Object.keys(e).length)return Result.fail("Invalid listing",e);
  return Result.ok({listing:Data.insert("commissions",{artistId:artist.id,title:d.title.trim(),price:+d.price,days:d.days||"",revisions:d.revisions||1,status:"LISTING"})});
 };
 S.getCommissionListing=id=>Data.get("commissions",id);
 S.getListings=aid=>Data.find("commissions",c=>c.artistId===aid&&c.status==="LISTING");
 S.submitCommissionBrief=(user,listingId,brief)=>{
  const g=RBAC.check(user,"commission.request");if(g)return g;
  const l=S.getCommissionListing(listingId);if(!l||l.status!=="LISTING")return Result.fail("Listing not found");
  if(String(brief||"").trim().length<10)return Result.fail("Invalid brief",{brief:"Describe what you want (10+ characters)"});
  const j=Data.insert("commissions",{listingId,artistId:l.artistId,buyerId:user.id,title:l.title,price:l.price,brief:brief.trim(),status:"BRIEF_SUBMITTED"});
  AuditLog.add({actorId:user.id,action:"COMMISSION_BRIEF_SUBMITTED",targetType:"commission",targetId:j.id});return Result.ok({job:j});
 };
 S.advanceCommission=(id,next,actor,who)=>{
  const j=Data.get("commissions",id);if(!j||j.status==="LISTING")return Result.fail("Commission not found");
  const okActor=actor&&(who==="artist"?actor.id===j.artistId:who==="buyer"?actor.id===j.buyerId:[j.artistId,j.buyerId].includes(actor.id));
  if(!okActor)return Result.fail("Not allowed for this commission");
  const t=StateMachine.transition(j.status,next,Const.COMMISSION);if(!t.ok)return t;
  AuditLog.add({actorId:actor.id,action:"COMMISSION_"+next,targetType:"commission",targetId:id});
  return Result.ok({job:Data.update("commissions",id,{status:next})});
 };
 S.acceptCommission=(id,a)=>S.advanceCommission(id,"ACCEPTED",a,"artist");
 S.rejectCommission=(id,a)=>S.advanceCommission(id,"REJECTED",a,"artist");
 S.startCommission=(id,a)=>S.advanceCommission(id,"IN_PROGRESS",a,"artist");
 S.completeCommission=(id,a)=>S.advanceCommission(id,"COMPLETED",a,"buyer");
 S.cancelCommission=(id,a)=>S.advanceCommission(id,"CANCELLED",a,"either");
 return S;
})();
