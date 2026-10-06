/* Data registry: the only place services read/write records. Phase 3+: back it with the Python API. */
var Data=(()=>{
 const seed={users:MockUsers,artworks:MockArtworks,orders:MockOrders,reviews:MockReviews,commissions:MockCommissions};
 const all=c=>{let v=AppStorage.get("db_"+c,null);if(v===null){v=JSON.parse(JSON.stringify(seed[c]||[]));AppStorage.set("db_"+c,v)}return v};
 const save=(c,l)=>AppStorage.set("db_"+c,l);
 return{
  getAll:all,
  get:(c,id)=>all(c).find(r=>r.id===id)||null,
  find:(c,fn)=>all(c).filter(fn),
  random:(c,fn)=>{const l=fn?all(c).filter(fn):all(c);return l.length?l[Math.floor(Math.random()*l.length)]:null},
  insert:(c,r)=>{const l=all(c);r.id=r.id||c.charAt(0)+Date.now().toString(36)+Math.random().toString(36).slice(2,5);l.push(r);save(c,l);return r},
  update:(c,id,patch)=>{const l=all(c),i=l.findIndex(r=>r.id===id);if(i<0)return null;l[i]=Object.assign(l[i],patch);save(c,l);return l[i]},
  remove:(c,id)=>{const l=all(c),n=l.filter(r=>r.id!==id);save(c,n);return n.length<l.length}
 };
})();
