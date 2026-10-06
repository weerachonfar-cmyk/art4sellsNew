/* Frontend RBAC is for UX only. The Python backend must re-check every permission. */
var RBAC={
 hasRole:(u,r)=>!!u&&u.role===r,
 hasPermission:(u,p)=>!!u&&(Const.PERMS[u.role]||[]).includes(p),
 check:(u,p)=>RBAC.hasPermission(u,p)?null:Result.fail("Permission denied: "+p),
 requirePermission:(u,p)=>{if(!RBAC.hasPermission(u,p)){const e=new Error("Permission denied: "+p);e.code="FORBIDDEN";throw e}}
};
