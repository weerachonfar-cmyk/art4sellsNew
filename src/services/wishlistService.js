var WishlistService=(()=>{
 const S={},list=k=>AppState.get(k,[]),toggle=(k,id)=>{const l=list(k),i=l.indexOf(id);i>-1?l.splice(i,1):l.push(id);AppState.set(k,l)};
 S.getWishlist=()=>list("wishlist");
 S.isWishlisted=id=>list("wishlist").includes(id);
 S.addToWishlist=id=>{if(!S.isWishlisted(id))toggle("wishlist",id)};
 S.removeFromWishlist=id=>{if(S.isWishlisted(id))toggle("wishlist",id)};
 S.isFollowing=id=>list("follows").includes(id);
 S.toggleFollow=id=>toggle("follows",id);
 return S;
})();
