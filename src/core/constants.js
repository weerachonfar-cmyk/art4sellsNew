var A4S=globalThis.A4S=globalThis.A4S||{};
var Result={ok:x=>Object.assign({ok:true},x),fail:(error,errors)=>({ok:false,error:error,errors:errors||{}})};
var Const={
 PERMS:{
  USER:["order.create","order.view","review.create","commission.request"],
  ARTIST:["order.create","order.view","review.create","commission.request","commission.manage","artwork.create","artwork.edit","artwork.delete"],
  ADMIN:["order.view","artwork.edit","artwork.delete","artwork.approve","artwork.manageAny","review.moderate","user.ban","user.blacklist","ip.block","audit.view"]
 },
 PUBLIC_STATUSES:["APPROVED","SOLD"],
 ARTWORK:{DRAFT:["PENDING_APPROVAL"],PENDING_APPROVAL:["APPROVED","REJECTED"],APPROVED:["SUSPENDED","SOLD"],REJECTED:["DRAFT"],SUSPENDED:["APPROVED"],SOLD:[]},
 ORDER:{CREATED:["PENDING_PAYMENT","CANCELLED"],PENDING_PAYMENT:["PAYMENT_VERIFIED","CANCELLED","EXPIRED"],PAYMENT_VERIFIED:["PAID"],PAID:["PROCESSING"],PROCESSING:["COMPLETED"],COMPLETED:[],CANCELLED:[],EXPIRED:[]},
 ACTIVE_ORDER:["CREATED","PENDING_PAYMENT","PAYMENT_VERIFIED","PAID","PROCESSING"],
 ORDER_TTL_MS:30*60*1000,
 COMMISSION:{LISTING:["BRIEF_SUBMITTED"],BRIEF_SUBMITTED:["PAYMENT_PENDING","CANCELLED"],PAYMENT_PENDING:["PAYMENT_VERIFIED","CANCELLED"],PAYMENT_VERIFIED:["ARTIST_REVIEW","REFUNDED"],ARTIST_REVIEW:["ACCEPTED","REJECTED"],ACCEPTED:["IN_PROGRESS","CANCELLED"],REJECTED:["REFUNDED"],IN_PROGRESS:["DELIVERED","CANCELLED"],DELIVERED:["COMPLETED"],COMPLETED:[],CANCELLED:["REFUNDED"],REFUNDED:[]}
};
A4S.cats=["Illustration","Digital Painting","3D Art","Character","Game Asset","Concept Art","Photography","Other"];
A4S.pal=[["#1d2b64","#f8cdda","#ffd6a5"],["#0f2027","#2c5364","#e8c07d"],["#3a1c71","#d76d77","#ffaf7b"],["#134e5e","#71b280","#f1f2b5"],["#232526","#b79891","#f3e7e9"],["#41295a","#2f0743","#e0a96d"],["#114357","#f29492","#fdeb71"],["#283048","#859398","#f5ebe0"]];
A4S.promos=[{big:"50% OFF",who:"Mika Sorn",txt:"Selected digital artwork",q:"a1"},{big:"Bundle -30%",who:"Kenji Aoi",txt:"Game asset packs",q:"a2"},{big:"New drop",who:"Lumi Pranee",txt:"Texture collection",q:"a4"}];
