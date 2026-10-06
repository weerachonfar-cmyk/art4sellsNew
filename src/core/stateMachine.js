var StateMachine={
 canTransition:(cur,next,rules)=>(rules[cur]||[]).includes(next),
 transition:(cur,next,rules)=>StateMachine.canTransition(cur,next,rules)?Result.ok({state:next}):Result.fail("Invalid transition: "+cur+" -> "+next)
};
