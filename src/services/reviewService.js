var ReviewService=(()=>{
 const S={};
 S.canUserReview=(u,aid)=>RBAC.hasPermission(u,"review.create")&&OrderService.hasPurchased(u.id,aid)&&!Data.find("reviews",r=>r.userId===u.id&&r.artworkId===aid).length;
 S.createReview=(u,d)=>{
  const v=Validation.validateReview(d);if(!v.valid)return Result.fail("Invalid review",v.errors);
  const w=Data.get("artworks",d.artworkId);if(!w)return Result.fail("Artwork not found");
  if(!S.canUserReview(u,d.artworkId))return Result.fail("Only buyers with a completed order can review, once per artwork");
  const r=Data.insert("reviews",{artworkId:w.id,artistId:w.artist,userId:u.id,rating:+d.rating,text:d.text.trim(),createdAt:new Date().toISOString().slice(0,10)});
  AuditLog.add({actorId:u.id,action:"REVIEW_CREATED",targetType:"review",targetId:r.id});return Result.ok({review:r});
 };
 S.getArtworkReviews=id=>Data.find("reviews",r=>r.artworkId===id);
 S.getArtistReviews=id=>Data.find("reviews",r=>r.artistId===id);
 S.calculateAverageRating=l=>l.length?Math.round(l.reduce((s,r)=>s+r.rating,0)/l.length*10)/10:0;
 return S;
})();
