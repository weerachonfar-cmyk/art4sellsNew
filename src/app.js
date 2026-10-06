/* Bootstrap + click/submit actions. Every action goes through A4S.api (real backend or mock fallback).
   Private actions (cart, wishlist, follow, notifications) first check that someone is logged in; the backend checks again. */
(function(){
 var pg=document.body.dataset.page,U=A4S.ui,api=function(){return A4S.api},me=function(){return AuthService.getCurrentUser()};
 var $=function(id){return document.getElementById(id)},firstError=function(r){return Object.values(r.errors||{})[0]||r.error};
 A4S.refresh=function(){$("hdr").innerHTML=U.header()};
 var render=function(){return A4S.pages[pg]?A4S.pages[pg]():null};
 var showError=function(e){$("app").innerHTML=U.fail(e&&e.message?e.message:"Unexpected error")};
 var rerender=function(){return Promise.resolve().then(render).catch(showError)};
 var NEED_LOGIN="\u0e01\u0e23\u0e38\u0e13\u0e32\u0e40\u0e02\u0e49\u0e32\u0e2a\u0e39\u0e48\u0e23\u0e30\u0e1a\u0e1a\u0e01\u0e48\u0e2d\u0e19\u0e08\u0e36\u0e07\u0e2a\u0e32\u0e21\u0e32\u0e23\u0e16\u0e43\u0e0a\u0e49\u0e1f\u0e31\u0e07\u0e01\u0e4c\u0e0a\u0e31\u0e19\u0e19\u0e35\u0e49\u0e44\u0e14\u0e49";
 /* Not logged in -> warn and go to Login. Nothing is created or remembered for the visitor. Returns true when blocked. */
 var blocked=function(){
  if(me())return false;
  U.toast(NEED_LOGIN);
  setTimeout(function(){location.href="login.html?next="+encodeURIComponent(location.pathname.split("/").pop()+location.search)},1200);
  return true;
 };
 var syncCart=async function(){var r=await api().cart.get();if(r.ok)A4S.priv.setCart(r.cart);A4S.refresh()};
 var reload=async function(){await A4S.priv.load();A4S.refresh()};
 A4S.refresh();
 A4S.ready.then(function(){
  A4S.refresh();   /* redraw now that the mode, the confirmed login and this user's private data are known */
  var f=document.querySelector("footer");if(f)f.textContent="Art 4 Sells. Finale Prototype: Marketplace, Commerce, Commission, Security. Mode: "+A4S.mode.toUpperCase();
  return render();
 }).catch(showError);

 /* CSP blocks inline onerror handlers, so a thumbnail that fails to load (no uploaded image yet) swaps to its data-fallback placeholder here */
 document.addEventListener("error",function(e){var t=e.target;if(t&&t.tagName==="IMG"&&t.dataset&&t.dataset.fallback){var fb=t.dataset.fallback;delete t.dataset.fallback;t.src=fb}},true);

 document.addEventListener("click",async function(e){
  var t=e.target,el,on=function(a){el=t.closest("["+a+"]");return el},r;
  try{
   if(on("data-heart")){e.preventDefault();if(blocked())return;var id=el.dataset.heart,has=A4S.priv.isWishlisted(id);
    r=has?await api().wishlist.remove(A4S.priv.wish[id]):await api().wishlist.add(id);
    if(!r.ok){U.toast(firstError(r));return}
    await reload();el.classList.toggle("on",!has);U.toast(has?"Removed from wishlist":"Saved to wishlist");if(pg==="wishlist")await rerender()}
   else if(on("data-add")){if(blocked())return;r=await api().cart.add(el.dataset.add);if(r.ok)await syncCart();U.toast(r.ok?"Added to cart":firstError(r))}
   else if(on("data-buy")){if(blocked())return;r=await api().cart.add(el.dataset.buy);if(r.ok)location.href="cart.html";else U.toast(firstError(r))}
   else if(on("data-rm")){r=await api().cart.remove(el.dataset.rm);if(!r.ok)U.toast(firstError(r));await syncCart();await rerender()}
   else if(on("data-qty")){var item=A4S.priv.cartItem(el.dataset.qty),q=item?item.quantity+ +el.dataset.d:0;
    r=q<1?await api().cart.remove(el.dataset.qty):await api().cart.setQty(el.dataset.qty,q);if(!r.ok)U.toast(firstError(r));await syncCart();await rerender()}
   else if(on("data-checkout")){if(blocked())return;r=await api().cart.checkout();
    await syncCart();U.toast(r.ok?"Order created. Payment pending.":firstError(r));await rerender()}
   else if(on("data-follow")){if(blocked())return;var aid=el.dataset.follow,fl=A4S.priv.isFollowing(aid);
    r=fl?await api().follows.remove(A4S.priv.follow[aid]):await api().follows.add(aid);
    if(!r.ok){U.toast(firstError(r));return}await reload();await rerender()}
   else if(on("data-commission-pay")){if(blocked())return;r=await api().commissions.submitPayment(el.dataset.commissionPay);U.toast(r.ok?"Commission payment submitted":firstError(r));if(r.ok)await rerender()}
   else if(on("data-commission-action")){if(blocked())return;r=await api().commissions.action(el.dataset.commissionAction,el.dataset.action);U.toast(r.ok?"Commission updated":firstError(r));if(r.ok)await rerender()}
   else if(on("data-commission-verify")){r=await api().commissions.verifyPayment(el.dataset.commissionVerify);U.toast(r.ok?"Commission payment verified":firstError(r));if(r.ok)await rerender()}
   else if(on("data-pay-reject")){if(!confirm("Reject this payment?"))return;r=await api().payments.verify(el.dataset.payReject,{approved:false,reason:"Slip rejected by admin"});U.toast(r.ok?"Payment rejected":firstError(r));if(r.ok)await rerender()}
   else if(on("data-pay-verify")){r=await api().payments.verify(el.dataset.payVerify,{approved:true});U.toast(r.ok?"Payment verified":firstError(r));if(r.ok)await rerender()}
   else if(on("data-black-remove")){r=await api().moderation.blacklistRemove(el.dataset.blackRemove);U.toast(r.ok?"Removed from blacklist":firstError(r));if(r.ok)await rerender()}
   else if(on("data-ip-remove")){r=await api().moderation.ipRemove(el.dataset.ipRemove);U.toast(r.ok?"IP block removed":firstError(r));if(r.ok)await rerender()}
   else if(on("data-decide")){var d=el.dataset.decide;r=el.dataset.v==="approve"?await api().artworks.approve(d):await api().artworks.reject(d);if(!r.ok)U.toast(firstError(r));await rerender()}
   else if(on("data-ban")){r=el.dataset.v==="ban"?await api().users.ban(el.dataset.ban):await api().users.unban(el.dataset.ban);U.toast(r.ok?"User updated":firstError(r));await rerender()}
   else if(on("data-art-edit")){var w=(A4S.myWorks||[]).find(function(x){return x.id===el.dataset.artEdit}),f=$("artForm");
    if(w&&f){f.elements.artId.value=w.id;f.elements.title.value=w.title;f.elements.price.value=w.price;f.elements.category.value=w.catId;f.elements.sale_type.value=w.type;
     f.elements.tags.value=w.tags.join(", ");f.elements.description.value=w.desc;$("formTitle").textContent="Edit artwork";f.querySelector("button").textContent="Update artwork";f.scrollIntoView({behavior:"smooth"})}}
   else if(on("data-art-submit")){r=await api().artworks.submit(el.dataset.artSubmit);U.toast(r.ok?"Submitted for approval":firstError(r));await rerender()}
   else if(on("data-art-del")){if(!confirm("Delete this artwork?"))return;r=await api().artworks.remove(el.dataset.artDel);U.toast(r.ok?"Artwork deleted":firstError(r));await rerender()}
   else if(on("data-notif")){r=await api().notifications.read(el.dataset.notif);if(!r.ok)U.toast(firstError(r));await rerender()}
   else if(on("data-notif-all")){r=await api().notifications.readAll();if(!r.ok)U.toast(firstError(r));await rerender()}
   /* ----- admin: Data Management (two steps: summary + token, then typed confirmation) ----- */
   else if(on("data-dm-reset-preview")){r=await api().dataAdmin.previewReset(true);
    if(!r.ok){U.toast(firstError(r));return}
    A4S.dm={kind:"reset",token:r.plan.confirm_token,preserve:true};$("dmStep").innerHTML=A4S.pages.dmPanel(r.plan,"reset");$("dmStep").scrollIntoView({behavior:"smooth"})}
   else if(on("data-dm-cancel")){A4S.dm=null;$("dmStep").innerHTML=""}
   else if(on("data-dm-continue")){$("dmConfirm").hidden=false;el.disabled=true;$("dmConfirm").scrollIntoView({behavior:"smooth"})}
   else if(t.closest("#menuBtn")||(t.closest("#profile")&&me())){e.preventDefault();$("menu").classList.toggle("open")}
   else if(t.closest("#logout")){e.preventDefault();await api().auth.logout();location.href="index.html"}
   else{var m=$("menu");if(m&&!t.closest("#menu"))m.classList.remove("open")}
  }catch(err){U.toast(err&&err.message?err.message:"Something went wrong")}
 });

 /* slip image preview (data: URL - the CSP does not allow blob:) */
 document.addEventListener("change",function(e){
  var t=e.target;if(!t||t.name!=="slip_file")return;
  var img=t.form&&t.form.querySelector(".slipPreview"),file=t.files&&t.files[0],perr=t.form&&t.form.querySelector(".err");
  if(!img)return;img.hidden=true;img.removeAttribute("src");if(perr)perr.textContent="";
  if(!file)return;
  var bad=api().artworks&&api().artworks.checkFile?api().artworks.checkFile(file):"";
  if(bad){if(perr)perr.textContent=bad;t.value="";return}
  var fr=new FileReader();fr.onload=function(){img.src=String(fr.result);img.hidden=false};fr.readAsDataURL(file)});
 document.addEventListener("submit",async function(e){
  var f=e.target,fid=f.getAttribute("id"),r;
  if(f.dataset&&f.dataset.busy==="1"){e.preventDefault();return}   /* ignore a second submit while the first is still running (double click) */
  if(f.dataset)f.dataset.busy="1";
  try{
   if(fid==="artForm"){e.preventDefault();var d=Object.fromEntries(new FormData(f)),id=d.artId,file=d.file&&d.file.size?d.file:null;delete d.artId;delete d.file;
    var badFile=file?api().artworks.checkFile(file):"";   /* check the image first so a bad file never leaves a half-created draft */
    if(badFile){$("artErr").textContent=badFile;return}
    r=id?await api().artworks.update(id,d):await api().artworks.create(d);
    if(!r.ok){$("artErr").textContent=firstError(r);return}
    if(file){var up=await api().artworks.uploadFile(id||r.artwork.id,file);
     if(!up.ok){await rerender();var ae=$("artErr");   /* the draft exists now: redraw the list, keep the reason visible */
      if(ae)ae.textContent=(id?"Artwork updated":"Saved as a draft")+", but the image was not uploaded: "+firstError(up);
      U.toast("Image upload failed");return}}
    U.toast(file?(id?"Artwork and image saved":"Draft and image saved"):(id?"Artwork updated":"Draft saved"));await rerender()}
   else if(fid==="reviewForm"){e.preventDefault();var v=Object.fromEntries(new FormData(f));
    r=await api().reviews.create({artworkId:f.dataset.art,artworkRating:Number(v.artworkRating),artistRating:Number(v.artistRating),rating:Number(v.artworkRating),text:v.text});
    if(!r.ok){$("revErr").textContent=firstError(r);return}
    U.toast("Review posted");await rerender()}
<<<<<<< HEAD
   else if(f.classList&&f.classList.contains("payForm")){e.preventDefault();var pv=Object.fromEntries(new FormData(f));r=await api().payments.submit(f.dataset.order,{order_id:f.dataset.order,method:pv.method,submitted_amount:Number(pv.amount),slip:(pv.slip||"").trim()});if(!r.ok){$("payErr-"+f.dataset.order).textContent=firstError(r);return}U.toast("Payment submitted for verification");await rerender()}
=======
   else if(f.classList&&f.classList.contains("payForm")){e.preventDefault();var pv=Object.fromEntries(new FormData(f)),perr=$("payErr-"+f.dataset.order),pfile=f.elements.slip_file&&f.elements.slip_file.files&&f.elements.slip_file.files[0],slipVal=(pv.slip||"").trim();
    perr.textContent="";
    if(pv.method!=="COD"&&pfile){   /* an image was chosen: upload it first, then submit the payment (the server links the newest slip image) */
     var up=await api().payments.uploadSlip(f.dataset.order,pfile);if(!up.ok){perr.textContent=firstError(up);return}slipVal=""}
    r=await api().payments.submit(f.dataset.order,{order_id:f.dataset.order,method:pv.method,submitted_amount:Number(pv.amount),slip:slipVal});
    if(!r.ok){perr.textContent=firstError(r);return}U.toast("Payment submitted for verification");await rerender()}
>>>>>>> 4bb6b93 (Block emoji in email, simulate slip by typing 'slip', fix payment/commission/admin forms)
   else if(fid==="commissionListingForm"){e.preventDefault();var cv=Object.fromEntries(new FormData(f)),payload={title:cv.title,description:cv.description,conditions:cv.conditions,price:Number(cv.price),days:Number(cv.days),revisions:Number(cv.revisions),samples:[]};r=await api().commissions.createListing(payload);if(!r.ok){$("commissionListingErr").textContent=firstError(r);return}U.toast("Commission listing created");await rerender()}
   else if(fid==="promotionForm"){e.preventDefault();var pv2=Object.fromEntries(new FormData(f)),prom={title:pv2.title,type:pv2.type,value:Number(pv2.value),start_at:new Date(pv2.start_at).toISOString(),end_at:new Date(pv2.end_at).toISOString(),artwork_id:pv2.artwork_id};if(!pv2.artwork_id)delete prom.artwork_id;r=await api().promotions.create(prom);if(!r.ok){$("promotionErr").textContent=firstError(r);return}U.toast("Promotion created");await rerender()}
   else if(fid==="blacklistForm"){e.preventDefault();var bv=Object.fromEntries(new FormData(f));r=await api().moderation.blacklistAdd({user_id:(bv.user_id||"").trim(),reason:(bv.reason||"").trim()});
    if(!r.ok){$("blackErr").textContent=firstError(r);return}U.toast("User blacklisted");await rerender()}
   else if(fid==="ipBlockForm"){e.preventDefault();var iv=Object.fromEntries(new FormData(f));r=await api().moderation.ipAdd({ip:(iv.ip||"").trim(),reason:(iv.reason||"").trim()});
    if(!r.ok){$("ipErr").textContent=firstError(r);return}U.toast("IP blocked");await rerender()}
   else if(fid==="commissionForm"){e.preventDefault();var mv=Object.fromEntries(new FormData(f));
    r=await api().commissions.create({listing_id:f.dataset.listing,payment_method:"QR_PAYMENT",brief:{type:mv.type,details:mv.details,references:mv.references,size:mv.size,style:mv.style,background:mv.background,character_count:Number(mv.character_count)||1,additional_requests:mv.additional_requests}});
    if(!r.ok){$("commissionErr").textContent=firstError(r);return}U.toast("Commission request created");location.href="orders.html"}
   else if(fid==="pwForm"){e.preventDefault();r=await api().password.change(Object.fromEntries(new FormData(f)));
    if(!r.ok){$("pwErr").textContent=firstError(r);return}
    U.toast("Password changed");await rerender()}
   else if(fid==="dmForm"){e.preventDefault();var fd=new FormData(f),scopes=fd.getAll("scope"),preserve=fd.get("preserve")==="on";
    if(!scopes.length){U.toast("Select at least one item");return}
    r=await api().dataAdmin.previewClear(scopes,preserve);
    if(!r.ok){U.toast(firstError(r));return}
    A4S.dm={kind:"clear",token:r.plan.confirm_token,scopes:scopes,preserve:preserve};$("dmStep").innerHTML=A4S.pages.dmPanel(r.plan,"clear");$("dmStep").scrollIntoView({behavior:"smooth"})}
   else if(fid==="dmConfirmForm"){e.preventDefault();var c=Object.fromEntries(new FormData(f)),dm=A4S.dm;
    if(!dm){U.toast("Start again");return}
    r=dm.kind==="clear"?await api().dataAdmin.clear({scopes:dm.scopes,preserve_admins:dm.preserve,confirm_token:dm.token,confirm_text:c.text,confirm_audit_text:c.audit})
      :await api().dataAdmin.reset({preserve_admins:dm.preserve,confirm_token:dm.token,confirm_text:c.text});
    if(!r.ok){$("dmErr").textContent=firstError(r);if(r.code==="CONFIRMATION_REQUIRED"){A4S.dm=null}return}
    A4S.dm=null;U.toast(dm.kind==="clear"?"Data cleared":"Demo data restored");await reload();await rerender()}
  }catch(err){U.toast(err&&err.message?err.message:"Something went wrong")}
  finally{if(f&&f.dataset)delete f.dataset.busy}
 });
})();
