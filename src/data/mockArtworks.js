var MockArtworks=[
["Moonlit Koi","a1","Illustration",1200,4.9,"LIMITED","APPROVED",["koi","night","ink"],"Ink and gouache koi drifting under a paper-white moon. One edition only."],
["Lantern Street","a1","Digital Painting",900,4.8,"LIMITED","APPROVED",["city","lantern","night"],"A rain-soaked alley glowing with hand-painted lanterns."],
["Fox Ranger","a1","Character",650,4.7,"UNLIMITED","APPROVED",["fox","fantasy","character"],"Forest ranger character sheet with full-colour and line-art layers."],
["Stone Golem Kit","a2","3D Art",1490,4.8,"UNLIMITED","APPROVED",["golem","lowpoly","rigged"],"Rigged low-poly golem with three texture sets. Commercial licence included."],
["Dungeon Prop Pack","a2","Game Asset",990,4.6,"UNLIMITED","APPROVED",["dungeon","props","modular"],"48 modular dungeon props with game-ready FBX files and PNG atlases."],
["Floating Isles","a2","3D Art",2200,4.9,"LIMITED","APPROVED",["island","sky","render"],"A cinematic render of drifting islands at dawn."],
["Ashen Citadel","a3","Concept Art",1800,5.0,"LIMITED","APPROVED",["castle","environment","matte"],"Matte-painted fortress rising from volcanic plains."],
["Tide Wraith","a3","Concept Art",1350,4.8,"LIMITED","SOLD",["creature","sea","design"],"Creature study with silhouette exploration and colour keys."],
["Wet Stone Textures","a4","Game Asset",450,4.5,"UNLIMITED","APPROVED",["texture","stone","seamless"],"12 seamless 4K PBR stone textures shot after monsoon rain."],
["Golden Hour, Ayutthaya","a4","Photography",800,4.7,"LIMITED","APPROVED",["photo","temple","sunset"],"Fine-art print file of ancient brick stupas at last light."],
["Paper Garden","a1","Illustration",700,4.6,"UNLIMITED","APPROVED",["flowers","paper","pastel"],"Layered paper-cut botanicals in a soft pastel palette."],
["Neon Courier","a3","Character",1100,4.7,"LIMITED","APPROVED",["cyberpunk","neon","character"],"Motorbike courier in a neon-soaked megacity, with full concept breakdown."],
["Sakura Mech","a2","3D Art",1600,0,"LIMITED","PENDING_APPROVAL",["mech","sakura","render"],"Cherry-blossom battle mech, high-poly render.","2026-09-28"],
["Salt Flat Dreams","a4","Photography",600,0,"UNLIMITED","PENDING_APPROVAL",["salt","desert","photo"],"Mirror-like salt flats at blue hour.","2026-09-29"],
["Ember Fox","a1","Character",750,0,"UNLIMITED","PENDING_APPROVAL",["fox","fire","character"],"Fire-spirit fox in a layered PSD.","2026-09-30"],
["Glass Harbour","a3","Concept Art",1400,0,"LIMITED","PENDING_APPROVAL",["harbour","glass","environment"],"A crystalline port city concept.","2026-09-30"]
].map((r,i)=>({id:"w"+(i+1),title:r[0],artist:r[1],cat:r[2],price:r[3],rating:r[4],type:r[5],status:r[6],tags:r[7],desc:r[8],seed:i%8,createdAt:"2026-09-"+("0"+(i+1)).slice(-2),submittedAt:r[9]}));
