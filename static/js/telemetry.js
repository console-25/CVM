/* Admin-only host telemetry; values and history come from successful samples. */
(() => {
 const root=document.querySelector('[data-host-telemetry]');if(!root)return;
 const label=root.querySelector('[data-host-updated]'),history={cpu:[],memory:[],disk:[],network:[]};
 let timer,busy=false,ended=false;
 function unavailable(message){label.textContent=message;root.querySelectorAll('[data-host-value]').forEach(el=>el.textContent='Unavailable');}
 async function refresh(){
  if(busy||document.hidden||ended)return;busy=true;
  try{
   const response=await fetch('/admin/host-telemetry',{headers:{Accept:'application/json'},signal:AbortSignal.timeout(12000)});
   if(!response.ok)throw Error();const data=await response.json();if(!data.success||!Number.isFinite(data.timestamp))throw Error();
   for(const key of Object.keys(history)){
    const value=data[key],cell=root.querySelector(`[data-host-cell="${key}"]`);if(!cell)continue;
    const valid=typeof value==='number'&&Number.isFinite(value);
    cell.querySelector('[data-host-value]').textContent=valid?(key==='network'?`${(value/1024).toFixed(1)} KiB/s`:`${value.toFixed(1)}%`):'Collecting…';
    const progress=cell.querySelector('progress');if(progress){progress.hidden=!valid;progress.value=value||0;}
    if(valid){history[key].push(value);if(history[key].length>36)history[key].shift();}
    const values=history[key],max=key==='network'?Math.max(1,...values):100;
    cell.querySelector('polyline')?.setAttribute('points',values.map((v,i)=>`${i/35*240},${39-v/max*35}`).join(' '));
   }
   label.textContent=`Live host sample · ${new Date(data.timestamp*1000).toLocaleTimeString()}`;
  }catch{unavailable('Host telemetry unavailable · retrying');}
  finally{busy=false;if(!ended)timer=setTimeout(refresh,15000);}
 }
 document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)refresh();});
 window.addEventListener('pagehide',()=>{ended=true;clearTimeout(timer);});
 window.addEventListener('pageshow',e=>{if(e.persisted){ended=false;refresh();}});
 refresh();
})();
