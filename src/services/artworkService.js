/* Artwork rules: visibility, ownership, approval workflow, search/filter/sort/paginate. */
var ArtworkService=(()=>{
 const S={},isPublic=w=>Const.PUBLIC_STATUSES.includes(w.status);
 const availability=w=>w.status==="SOLD"?"Sold":(w.type==="LIMITED"&&OrderService.hasActiveOrderFor(w.id))?"Processing":"Available";
 const view=w=>w&&Object.assign({},w,{availability:availability(w)});
 const owns=(w,a)=>!!a&&(w.artist===a.id||RBAC.hasPermission(a,"artwork.manageAny"));
 const audit=(a,act,id)=>AuditLog.add({actorId:a?a.id:"system",action:act,targetType:"artwork",targetId:id});
 const pick=(d,keys)=>{const o={};keys.forEach(k=>{if(d[k]!==undefined)o[k]=d[k]});return o};
 const FIELDS=["title","price","cat","type","tags","desc"];
 S.getArtwork=id=>{const w=Data.get("artworks",id);return w&&isPublic(w)?view(w):null};
 S.getAllArtworks=()=>Data.find("artworks",isPublic).map(view);
 S.getSubmissions=()=>Data.find("artworks",w=>!!w.submittedAt);
 S.createArtwork=(d,actor)=>{
  const g=RBAC.check(actor,"artwork.create");if(g)return g;
  const v=Validation.validateArtwork(d);if(!v.valid)return Result.fail("Invalid artwork",v.errors);
  const w=Data.insert("artworks",Object.assign(pick(d,FIELDS),{title:d.title.trim(),price:+d.price,tags:d.tags||[],desc:d.desc||"",artist:actor.id,status:"DRAFT",rating:0,seed:Math.floor(Math.random()*8),createdAt:new Date().toISOString().slice(0,10)}));
  audit(actor,"ARTWORK_CREATED",w.id);return Result.ok({artwork:w});
 };
 S.updateArtwork=(id,patch,actor)=>{
  const g=RBAC.check(actor,"artwork.edit");if(g)return g;
  const w=Data.get("artworks",id);if(!w)return Result.fail("Artwork not found");
  if(!owns(w,actor))return Result.fail("Not your artwork");
  const merged=Object.assign({},w,pick(patch,FIELDS)),v=Validation.validateArtwork(merged);
  if(!v.valid)return Result.fail("Invalid artwork",v.errors);
  audit(actor,"ARTWORK_UPDATED",id);return Result.ok({artwork:Data.update("artworks",id,pick(merged,FIELDS))});
 };
 S.deleteArtwork=(id,actor)=>{
  const g=RBAC.check(actor,"artwork.delete");if(g)return g;
  const w=Data.get("artworks",id);if(!w)return Result.fail("Artwork not found");
  if(!owns(w,actor))return Result.fail("Not your artwork");
  Data.remove("artworks",id);audit(actor,"ARTWORK_DELETED",id);return Result.ok({});
 };
 const move=(id,next,actor,perm,act,mustOwn)=>{
  const g=RBAC.check(actor,perm);if(g)return g;
  const w=Data.get("artworks",id);if(!w)return Result.fail("Artwork not found");
  if(mustOwn&&!owns(w,actor))return Result.fail("Not your artwork");
  const t=StateMachine.transition(w.status,next,Const.ARTWORK);if(!t.ok)return t;
  const patch={status:next};if(next==="PENDING_APPROVAL")patch.submittedAt=new Date().toISOString().slice(0,10);
  audit(actor,act,id);return Result.ok({artwork:Data.update("artworks",id,patch)});
 };
 S.submitForApproval=(id,a)=>move(id,"PENDING_APPROVAL",a,"artwork.edit","ARTWORK_SUBMITTED",true);
 S.approveArtwork=(id,a)=>move(id,"APPROVED",a,"artwork.approve","ARTWORK_APPROVED",false);
 S.rejectArtwork=(id,a)=>move(id,"REJECTED",a,"artwork.approve","ARTWORK_REJECTED",false);
 S.markSold=id=>{const w=Data.get("artworks",id);if(w&&StateMachine.canTransition(w.status,"SOLD",Const.ARTWORK)){Data.update("artworks",id,{status:"SOLD"});audit(null,"ARTWORK_SOLD",id)}};
 const match=(list,q,type)=>{q=String(q||"").trim().toLowerCase();if(!q)return list;
  return list.filter(w=>String(type==="artist"?(AuthService.getUser(w.artist)||{}).name:type==="tag"?w.tags.join(" "):w.title).toLowerCase().includes(q))};
 S.filterArtworks=(list,f)=>list.filter(w=>(!f.category||w.cat===f.category)&&(!f.minRating||w.rating>=+f.minRating)&&(!f.maxPrice||w.price<=+f.maxPrice)&&(!f.minPrice||w.price>=+f.minPrice)&&(!f.saleType||w.type===f.saleType)&&(!f.artist||w.artist===f.artist));
 S.sortArtworks=(list,key)=>{
  const by={newest:(a,b)=>b.createdAt.localeCompare(a.createdAt),oldest:(a,b)=>a.createdAt.localeCompare(b.createdAt),priceAsc:(a,b)=>a.price-b.price,priceDesc:(a,b)=>b.price-a.price,rating:(a,b)=>b.rating-a.rating}[key];
  return by?list.slice().sort(by):list;
 };
 S.paginateArtworks=(list,page,size)=>{size=size||8;const tp=Math.max(1,Math.ceil(list.length/size)),p=Math.min(Math.max(1,+page||1),tp);return{items:list.slice((p-1)*size,p*size),total:list.length,page:p,pageSize:size,totalPages:tp}};
 S.searchArtworks=o=>{o=o||{};return S.paginateArtworks(S.sortArtworks(S.filterArtworks(match(S.getAllArtworks(),o.query,o.type),o.filters||{}),o.sort),o.page,o.pageSize)};
 return S;
})();
