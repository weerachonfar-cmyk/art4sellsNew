var MockCommissions=[];
["a1","a2","a4"].forEach(a=>[["Head Shot",500,"3-7 days",2],["Half Body",800,"5-10 days",2],["Full Body",1500,"7-14 days",3]].forEach((t,i)=>MockCommissions.push({id:"cl_"+a+"_"+i,artistId:a,title:t[0],price:t[1],days:t[2],revisions:t[3],status:"LISTING"})));
