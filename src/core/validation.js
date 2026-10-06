/* Every validator is UI-free. validateXxx(data) returns {valid, errors:{field:message}}. */
var Validation=(()=>{
 const V={},pack=m=>{const e={};Object.keys(m).forEach(k=>{if(m[k])e[k]=m[k]});return{valid:!Object.keys(e).length,errors:e}};
 V.validateRequired=(v,l)=>String(v==null?"":v).trim()?"":(l||"This field")+" is required";
 V.validateEmail=v=>{v=typeof v==="string"?v.trim():"";if(/[^\x00-\x7F]/.test(v))return"Email may use only English letters, numbers and . _ % + - (no emoji)";return /^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z0-9-]{2,}$/.test(v)?"":"Enter a valid email address"};
 /* Password policy (UX only - the Python backend is the real check): 8-128 chars + a-z, A-Z, 0-9, special. Never trim/lower/alter the value. */
 V.PASSWORD_RULES=[
  {text:"At least 8 characters",error:"Password must be at least 8 characters",ok:p=>p.length>=8},
  {text:"One uppercase letter",error:"Password must contain an uppercase letter",ok:p=>/[A-Z]/.test(p)},
  {text:"One lowercase letter",error:"Password must contain a lowercase letter",ok:p=>/[a-z]/.test(p)},
  {text:"One number",error:"Password must contain a number",ok:p=>/[0-9]/.test(p)},
  {text:"One special character",error:"Password must contain a special character",ok:p=>/[!-\/:-@\[-`{-~]/.test(p)}
 ];
 V.validatePassword=v=>{const p=typeof v==="string"?v:"";if(p.length>128)return"Password must be at most 128 characters";const bad=V.PASSWORD_RULES.find(r=>!r.ok(p));return bad?bad.error:""};
 V.validateUsername=v=>/^[\w .-]{2,30}$/.test(String(v||"").trim())?"":"Display name must be 2-30 characters";
 V.validatePrice=v=>isFinite(v)&&+v>0&&+v<=1000000?"":"Price must be greater than 0";
 V.validateArtwork=d=>pack({title:V.validateRequired(d.title,"Title")||(String(d.title).length>80?"Title is too long":""),price:V.validatePrice(d.price),cat:A4S.cats.includes(d.cat)?"":"Choose a category",type:["LIMITED","UNLIMITED"].includes(d.type)?"":"Choose a sale type"});
 V.validateLogin=d=>pack({email:V.validateEmail(d.email),password:typeof d.password==="string"&&d.password.length?"":"Enter your password"});   /* no password policy at login */
 V.validateRegistration=d=>pack({name:V.validateUsername(d.name),email:V.validateEmail(d.email),password:V.validatePassword(d.password),confirm:d.confirm===d.password?"":"Passwords do not match",role:["USER","ARTIST"].includes(d.role)?"":"Choose USER or ARTIST"});
 V.validateReview=d=>pack({rating:Number.isInteger(+d.rating)&&d.rating>=1&&d.rating<=5?"":"Rating must be 1 to 5",text:String(d.text||"").trim().length>=5?"":"Write at least 5 characters"});
 return V;
})();
