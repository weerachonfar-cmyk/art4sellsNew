/* Only file that touches localStorage. Phase 3+: swap for API calls. (Named AppStorage to avoid the browser's built-in Storage.) */
var AppStorage=(()=>{const P="a4s_";return{
 get:(k,d)=>{try{const v=localStorage.getItem(P+k);return v===null?d:JSON.parse(v)}catch(e){return d}},
 set:(k,v)=>{try{localStorage.setItem(P+k,JSON.stringify(v));return true}catch(e){return false}},
 remove:k=>{try{localStorage.removeItem(P+k)}catch(e){}},
 clear:()=>{try{for(let i=localStorage.length-1;i>=0;i--){const k=localStorage.key(i);if(k&&k.indexOf(P)===0)localStorage.removeItem(k)}}catch(e){}}
}})();
