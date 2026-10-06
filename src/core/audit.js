var AuditLog={
 add:e=>{const l=AppStorage.get("audit",[]);l.push({actorId:e.actorId||null,action:e.action,targetType:e.targetType||null,targetId:e.targetId||null,timestamp:new Date().toISOString(),metadata:e.metadata||{}});AppStorage.set("audit",l.slice(-500))},
 list:a=>AppStorage.get("audit",[]).filter(x=>!a||x.action===a)
};
