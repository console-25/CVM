/* Progressive enhancement: the original form and submission API stay authoritative. */
(() => {
 'use strict';
 const form = document.getElementById('createVPSForm');
 if (!form) return;
 const get = id => document.getElementById(id);
 const initialGrid = form.querySelector(':scope > .grid');
 const originalCards = Array.from(form.children).filter(el => el.classList.contains('card'));
 const submit = form.querySelector('button[type="submit"]');
 const originalActions = submit.parentElement;
 const cancel = originalActions.querySelector('a');
 const titles = ['System', 'Resources', 'Network', 'Access', 'Review'];
 const descriptions = ['Choose an owner, deployment node and operating system.', 'Allocate compute, storage and retention limits.', 'Choose how this server connects to the network.', 'Choose a guest account and how you authenticate.', 'Check every allocation before creating the server.'];
 const steps = document.createElement('ol'); steps.className='provision-steps'; steps.setAttribute('aria-label','Creation steps');
 const layout=document.createElement('div');layout.className='provision-layout';
 const body=document.createElement('div');body.className='provision-body';
 const stages=titles.map((title,index)=>{
  const item=document.createElement('li'),button=document.createElement('button');button.type='button';
  const number=document.createElement('b');number.textContent=String(index+1);button.append(number,document.createTextNode(title));
  button.setAttribute('aria-controls','provision-step-'+index);item.append(button);steps.append(item);
  const section=document.createElement('section');section.className='provision-stage';section.id='provision-step-'+index;
  const heading=document.createElement('h2');heading.textContent=title==='Review'?'Review configuration':title+' configuration';heading.tabIndex=-1;
  const description=document.createElement('p');description.textContent=descriptions[index];section.append(heading,description);body.append(section);
  return {section,button,heading};
 });
 const systemGrid=document.createElement('div');systemGrid.className='grid grid-2';stages[0].section.append(systemGrid);
 const resourcesGrid=document.createElement('div');resourcesGrid.className='grid grid-2';stages[1].section.append(resourcesGrid);
 for (const id of ['user_id','node_id','hostname','os_version']) systemGrid.append(get(id).closest('.form-group'));
 for (const id of ['cpu','ram','disk']) resourcesGrid.append(get(id).closest('.form-group'));
 // Preserve the disabled swap field and all original listeners/IDs.
 while(initialGrid.firstElementChild) initialGrid.firstElementChild.remove();
 initialGrid.remove();
 function moveCard(id,stage,collapsed=false) {
  const card=originalCards.find(el=>el.querySelector('#'+id));if(!card)return;
  if(collapsed){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Advanced: nested virtualization';details.append(summary,card);stages[stage].section.append(details);}
  else stages[stage].section.append(card);
 }
 moveCard('kvm_enabled',1,true);
 for(const id of ['bandwidth_quota_gb','snapshot_limit']){const card=originalCards.find(el=>el.querySelector('#'+id));if(card){resourcesGrid.append(get(id).closest('.form-group'));card.remove();}}moveCard('network_mode',2);moveCard('auto_suspend_enabled',2);moveCard('access_mode',3);
 const summaryCard=originalCards.find(el=>el.querySelector('#summary-cpu'));
 if(summaryCard) stages[4].section.append(summaryCard);
 // Existing summary nodes remain live; hide the verbose swap label without losing it.
 const review=document.createElement('div');review.className='provision-review';
 const reviewList=document.createElement('dl');review.append(reviewList);stages[4].section.insertBefore(review, summaryCard || null);
 const note=document.createElement('p');note.className='provision-review-note';note.textContent='The panel will provision the guest and verify its network and SSH service. Credentials become available after setup. Shared IPv4 uses the node address and mapped ports.';stages[4].section.append(note);
 const preview=document.createElement('aside');preview.className='provision-preview';preview.setAttribute('aria-label','Configuration preview');
 const previewHeading=document.createElement('h3');previewHeading.textContent='Configuration preview';
 const avatar=document.createElement('div');avatar.className='provision-avatar';avatar.innerHTML='<i class="fas fa-server" aria-hidden="true"></i>';
 const previewName=document.createElement('strong'),previewOS=document.createElement('p'),previewList=document.createElement('dl');
 const previewNote=document.createElement('small');previewNote.textContent='This preview reflects your form values. Capacity and permissions are checked by the server when you deploy.';
 preview.append(previewHeading,avatar,previewName,previewOS,previewList,previewNote);layout.append(body,preview);
 const actions=document.createElement('div');actions.className='provision-actions';
 const back=document.createElement('button');back.type='button';back.className='btn btn-outline provision-back';back.textContent='Back';
 const next=document.createElement('button');next.type='button';next.className='btn btn-primary provision-next';next.textContent='Continue';
 submit.classList.add('provision-submit');submit.innerHTML='<i class="fas fa-plus" aria-hidden="true"></i> Create server';
 actions.append(cancel,back,next,submit);body.append(actions);originalActions.remove();form.prepend(steps,layout);
 const os=get('os_version');const osGroup=os.closest('.form-group');
 const tiles=document.createElement('div');tiles.className='provision-os-tiles';tiles.setAttribute('aria-label','Operating systems');
 Array.from(os.options).filter(option=>option.value).forEach(option=>{
  const button=document.createElement('button');button.type='button';button.dataset.os=option.value;
  const icon=document.createElement('i');icon.className='fab fa-'+(/ubuntu/i.test(option.text)?'ubuntu':/fedora/i.test(option.text)?'fedora':/centos/i.test(option.text)?'centos':'linux');icon.setAttribute('aria-hidden','true');
  const label=document.createElement('span');label.textContent=option.text.trim();button.append(icon,label);
  button.addEventListener('click',()=>{os.value=option.value;os.dispatchEvent(new Event('change',{bubbles:true}));});tiles.append(button);
 });
 if(tiles.children.length)osGroup.append(tiles);
 // Explicit labels also serve keyboard and screen-reader users.
 form.querySelectorAll('.form-group').forEach(group=>{const control=group.querySelector('input[id],select[id]');const label=group.querySelector('label');if(control&&label&&!label.htmlFor)label.htmlFor=control.id;});
 let current=0;
 function selected(id){const field=get(id);return field.selectedOptions?.[0]?.textContent.trim()||'Not selected';}
 function rows(target,values){target.replaceChildren();for(const [label,value]of values){const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;row.append(dt,dd);target.append(row);}}
 function update(){
  const key=get('access_mode').value==='key';get('ssh-key-group').hidden=!key;get('ssh_public_key').required=key;get('ssh_public_key').disabled=!key;get('ssh_username').readOnly=!key;if(!key)get('ssh_username').value='root';
  get('access-policy-explanation').textContent=key?'Key-only SSH access. Password login is disabled. Keep your private key on your computer, or use it for a single browser-console session.':'A unique strong root password is generated for this VPS and encrypted in the panel. Retrieve it after setup. Existing authorized keys remain usable.';
  previewName.textContent=get('hostname').value.trim()||'New virtual server';previewOS.textContent=selected('os_version');
  const allocation=[['CPU',get('cpu').value+' vCPU'],['Memory',get('ram').value+' GB'],['Storage',get('disk').value+' GB'],['Network',get('network_mode').value==='shared'?'Shared IPv4 / NAT':get('network_mode').value==='existing'?'Existing profile network':'Dedicated routed IPv4']];
  rows(previewList,allocation);rows(reviewList,[['Hostname',get('hostname').value.trim()||'Auto-generated'],['Owner',selected('user_id')],['Node',selected('node_id')],['Operating system',selected('os_version')],['SSH authentication',selected('access_mode')],['SSH username',get('ssh_username').value],...allocation,['Bandwidth',get('bandwidth_quota_gb').value==='0'?'Unlimited':get('bandwidth_quota_gb').value+' GB'],['Snapshot limit',get('snapshot_limit').value],['Nested virtualization',get('kvm_enabled').checked?'Enabled':'Disabled'],['Expiration',get('auto_suspend_enabled').checked?get('expiration_days').value+' days':'No automatic expiration'],...(get('network_mode').value==='dedicated'?[['Routed address',get('ip_address').value||'Not set']]:[])]);
  tiles.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.os===os.value)));
 }
 function validate(index){
  for(const field of stages[index].section.querySelectorAll('input,select,textarea')){
   if(!field.disabled && !field.checkValidity()){show(index,false);field.reportValidity();return false;}
  }
  if(index===2 && get('network_mode').value==='dedicated' && !get('ip_address').value.trim()){
   show(index,false);get('ip_address').setCustomValidity('Enter a separate provider-routed IPv4 address.');get('ip_address').reportValidity();return false;
  }
  return true;
 }
 function show(index,focus=true){
  current=index;stages.forEach((stage,i)=>{stage.section.hidden=i!==index;stage.button.classList.toggle('is-complete',i<index);if(i===index)stage.button.setAttribute('aria-current','step');else stage.button.removeAttribute('aria-current');});
  back.hidden=index===0;next.hidden=index===4;submit.hidden=index!==4;update();if(focus)stages[index].heading.focus({preventScroll:true});
 }
 form.noValidate=true;
 next.addEventListener('click',()=>{if(validate(current))show(Math.min(4,current+1));});back.addEventListener('click',()=>show(Math.max(0,current-1)));
 stages.forEach((stage,index)=>stage.button.addEventListener('click',()=>{if(index>current){for(let i=0;i<index;i++)if(!validate(i))return;}show(index);}));
 form.addEventListener('input',()=>{get('ip_address').setCustomValidity('');update();});form.addEventListener('change',update);
 form.addEventListener('submit',event=>{
  if(current<4){event.preventDefault();event.stopImmediatePropagation();if(validate(current))show(current+1);return;}
  for(let i=0;i<4;i++)if(!validate(i)){event.preventDefault();event.stopImmediatePropagation();return;}
 },true);
 const imageCheck=get('check-image'),imageStatus=get('image-availability');
 imageCheck?.addEventListener('click',async()=>{
  const node=get('node_id').value,image=os.value;if(!node){imageStatus.textContent='Select a node first.';return;}
  imageCheck.disabled=true;imageCheck.setAttribute('aria-busy','true');imageStatus.textContent='Checking image metadata on the node…';
  try{
   const response=await fetch(`/admin/nodes/${encodeURIComponent(node)}/image-availability?image=${encodeURIComponent(image)}`,{signal:AbortSignal.timeout(35000),headers:{Accept:'application/json'}});
   const result=await response.json();if(!response.ok||!result.success)throw Error(result.error||'Image lookup unavailable.');
   if(get('node_id').value!==node||os.value!==image)return;
   imageStatus.textContent=result.available?`Available: ${result.image}${result.fallback?' (fallback image)':''}`:result.error;
  }catch(error){imageStatus.textContent=error.message||'Image lookup unavailable. Check node connectivity.';}
  finally{imageCheck.disabled=false;imageCheck.removeAttribute('aria-busy');}
 });
 for(const control of [os,get('node_id')])control.addEventListener('change',()=>{imageStatus.textContent='Availability is checked on the node before deployment.';});
 show(0,false);
})();
