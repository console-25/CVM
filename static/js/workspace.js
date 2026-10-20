(() => {
  'use strict';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduced) { document.documentElement.classList.add('has-motion'); document.querySelectorAll('[data-reveal]').forEach((el, i) => el.style.setProperty('--reveal-delay', `${Math.min(i % 6, 5) * 40}ms`)); }
  window.workspaceToast = (message, tone = 'info') => {
    let el = document.getElementById('workspace-toast');
    if (!el) { el = document.createElement('div'); el.id = 'workspace-toast'; el.setAttribute('role', 'status'); document.body.append(el); }
    el.textContent = message; el.dataset.tone = tone; el.hidden = false;
    clearTimeout(window.workspaceToast.timer); window.workspaceToast.timer = setTimeout(() => el.hidden = true, 3500);
  };
  window.workspaceCopy = async text => {
    try { await navigator.clipboard.writeText(text); workspaceToast('Copied to clipboard'); }
    catch { workspaceToast('Clipboard unavailable. Select and copy the text manually.'); }
  };
  const command = document.getElementById('workspace-command');
  const search = command?.querySelector('input');
  const results = command?.querySelector('.command-results');
  if (command && results) {
    const seen = new Set();
    document.querySelectorAll('.sidebar .nav-item').forEach(link => {
      if (seen.has(link.href)) return; seen.add(link.href);
      const item = link.cloneNode(true); item.className = ''; item.querySelectorAll('.badge').forEach(x => x.remove()); results.append(item);
    });
    const open = () => { if (!command.open) command.showModal(); search.value = ''; results.querySelectorAll('a').forEach(a => a.hidden = false); search.focus(); };
    document.querySelector('[data-command-open]')?.addEventListener('click', open);
    document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); command.open ? command.close() : open(); } });
    search.addEventListener('input', () => results.querySelectorAll('a').forEach(a => a.hidden = !a.textContent.toLowerCase().includes(search.value.toLowerCase())));
    search.addEventListener('keydown', e => { if (e.key === 'ArrowDown') { e.preventDefault(); results.querySelector('a:not([hidden])')?.focus(); } });
    command.addEventListener('click', e => { if (e.target === command) command.close(); });
  }
  const toggle = document.getElementById('menuToggle');
  if (toggle) {
    toggle.setAttribute('aria-label', 'Toggle navigation'); toggle.setAttribute('aria-controls', 'sidebar');
    const sync = () => toggle.setAttribute('aria-expanded', String(document.getElementById('sidebar').classList.contains('mobile-open')));
    new MutationObserver(sync).observe(document.getElementById('sidebar'), {attributes:true, attributeFilter:['class']}); sync();
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { document.getElementById('sidebar').classList.remove('mobile-open'); sync(); } });
  }
  document.querySelectorAll('.nav-item.active').forEach(x => x.setAttribute('aria-current', 'page'));
  const sidebar=document.getElementById('sidebar');
  if(sidebar){
    const collapse=document.createElement('button');collapse.className='sidebar-collapse';collapse.type='button';collapse.innerHTML='<i class="fas fa-angles-left" aria-hidden="true"></i> <span>Collapse navigation</span>';collapse.setAttribute('aria-label','Collapse or expand sidebar');
    function compact(value){document.documentElement.classList.toggle('sidebar-compact',value);collapse.setAttribute('aria-expanded',String(!value));try{localStorage.setItem('hvm.sidebar.compact',String(value));}catch{}}
    try{compact(localStorage.getItem('hvm.sidebar.compact')==='true');}catch{}
    collapse.addEventListener('click',()=>compact(!document.documentElement.classList.contains('sidebar-compact')));sidebar.append(collapse);
    sidebar.querySelectorAll('.nav-item').forEach(link=>link.title=link.textContent.trim());
  }
  for(const [buttonId,panelId] of [['userMenuBtn','userDropdown'],['notificationsBtn','notificationsPanel']]){
    const button=document.getElementById(buttonId),panel=document.getElementById(panelId);if(!button||!panel)continue;
    button.setAttribute('aria-label',buttonId==='userMenuBtn'?'Account menu':'Notifications');button.setAttribute('aria-controls',panelId);button.setAttribute('aria-expanded','false');
    const observer=new MutationObserver(()=>button.setAttribute('aria-expanded',String(panel.classList.contains('show'))));observer.observe(panel,{attributes:true,attributeFilter:['class']});
    panel.addEventListener('keydown',event=>{if(event.key==='Escape'){panel.classList.remove('show');button.focus();}});
  }
  // Legacy modal pages share the same focus and keyboard behavior as native dialogs.
  const modalFocus=new WeakMap();
  document.querySelectorAll('.modal').forEach(modal=>{
    modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');
    const heading=modal.querySelector('h2,h3,h4');if(heading){heading.id ||= `${modal.id}-title`;modal.setAttribute('aria-labelledby',heading.id);}
    new MutationObserver(()=>{
      if(modal.classList.contains('show')){modalFocus.set(modal,document.activeElement);modal.querySelector('input:not([disabled]),button:not([disabled]),select,textarea')?.focus();}
      else {const previous=modalFocus.get(modal);if(previous?.isConnected)previous.focus({preventScroll:true});modalFocus.delete(modal);}
    }).observe(modal,{attributes:true,attributeFilter:['class']});
  });
  document.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const modal=[...document.querySelectorAll('.modal.show')].at(-1)||(sidebar?.classList.contains('mobile-open')?sidebar:null);if(!modal)return;
    const controls=[...modal.querySelectorAll('a[href],button,input,select,textarea,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);
    if(!controls.length)return;
    const first=controls[0],last=controls.at(-1);
    if(event.shiftKey&&(!modal.contains(document.activeElement)||document.activeElement===first)){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&(!modal.contains(document.activeElement)||document.activeElement===last)){event.preventDefault();first.focus();}
  });
  if (!document.querySelector('[data-server-workspace]')) return;
  const cards=[...document.querySelectorAll('[data-server-id]')],grid=document.querySelector('.server-grid');
  const find=document.querySelector('[data-server-search]'),filter=document.querySelector('[data-server-filter]'),sort=document.querySelector('[data-server-sort]');
  const prev=document.querySelector('[data-page-prev]'),next=document.querySelector('[data-page-next]'),pageLabel=document.querySelector('[data-page-label]');
  const refreshButton=document.querySelector('[data-server-refresh]');let page=0;const pageSize=9;
  function filterCards(reset=false){
    if(reset)page=0;
    const selected=cards.filter(card=>card.dataset.serverName.includes((find?.value||'').toLowerCase())&&(filter?.value==='all'||card.dataset.serverStatus===filter?.value));
    selected.sort((a,b)=>sort?.value==='name'?a.dataset.serverName.localeCompare(b.dataset.serverName):(a.dataset.serverCreated||'').localeCompare(b.dataset.serverCreated||'')*(sort?.value==='oldest'?1:-1));
    page=Math.min(page,Math.max(0,Math.ceil(selected.length/pageSize)-1));cards.forEach(card=>card.hidden=true);
    selected.slice(page*pageSize,(page+1)*pageSize).forEach(card=>{grid.append(card);card.hidden=false;});
    document.querySelector('[data-search-empty]').hidden=selected.length>0||cards.length===0;
    if(pageLabel)pageLabel.textContent=selected.length?`${page*pageSize+1}–${Math.min((page+1)*pageSize,selected.length)} of ${selected.length} instances`:'No instances';
    if(prev)prev.disabled=page===0;if(next)next.disabled=(page+1)*pageSize>=selected.length;
  }
  find?.addEventListener('input',()=>filterCards(true));filter?.addEventListener('change',()=>filterCards(true));sort?.addEventListener('change',()=>filterCards(true));
  prev?.addEventListener('click',()=>{page--;filterCards();});next?.addEventListener('click',()=>{page++;filterCards();});filterCards();
  let timer,busy=false,stopped=false;
  const label=document.querySelector('[data-refresh-label]');
  function unavailable(card){card.dataset.stale='true';card.querySelector('[data-server-state]').textContent='Unknown · last check failed';card.querySelector('.state-pill').dataset.state='unknown';card.dataset.serverStatus='unknown';for(const key of ['cpu','ram'])card.querySelector(`[data-server-${key}]`).textContent='—';}
  async function refresh(){
    clearTimeout(timer);
    if(busy||document.hidden||stopped||!cards.length){if(!cards.length&&label)label.textContent='';return;}
    busy=true;if(refreshButton){refreshButton.disabled=true;refreshButton.setAttribute('aria-busy','true');}
    try{
      const response=await fetch('/dashboard/stats',{signal:AbortSignal.timeout(20000),headers:{Accept:'application/json'}});
      if(!response.ok)throw Error();const data=await response.json();if(!data.success)throw Error();
      let stale=false;const counts={running:0,stopped:0};
      cards.forEach(card=>{
        const stat=data.stats[card.dataset.serverId];if(!stat||stat.connection_issue){unavailable(card);stale=true;return;}
        const state=['running','stopped','suspended','installing','reinstalling','failed','missing','frozen'].includes(stat.status)?stat.status:'unknown';
        card.dataset.stale='false';card.dataset.serverStatus=state;card.querySelector('[data-server-state]').textContent=state;card.querySelector('.state-pill').dataset.state=state;if(state in counts)counts[state]++;
        card.querySelector('[data-server-cpu]').textContent=state==='running'&&typeof stat.cpu==='number'?`${stat.cpu.toFixed(1)}%`:'—';
        card.querySelector('[data-server-ram]').textContent=state==='running'&&typeof stat.ram?.pct==='number'?`${stat.ram.pct.toFixed(1)}%`:'—';
        if(stat.ipv4!==undefined)card.querySelector('[data-server-ipv4]').textContent=stat.ipv4||'No IPv4 assigned';
        if(stat.ipv6!==undefined)card.querySelector('[data-server-ipv6]').textContent=stat.ipv6||'';
      });
      document.querySelectorAll('[data-fleet-count]').forEach(el=>{el.textContent=stale?'—':counts[el.dataset.fleetCount];const note=el.parentElement.querySelector('p');if(note)note.textContent=stale?'Some instance states unavailable':'Verified live instance state';});
      if(label)label.textContent=stale?'Some states unavailable · retrying':`Updated ${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}`;
      filterCards();
    }catch{cards.forEach(unavailable);document.querySelectorAll('[data-fleet-count]').forEach(el=>el.textContent='—');if(label)label.textContent='Connection lost · retrying';filterCards();}
    finally{busy=false;if(refreshButton){refreshButton.disabled=false;refreshButton.removeAttribute('aria-busy');}if(!stopped)timer=setTimeout(refresh,15000);}
  }
  refreshButton?.addEventListener('click',refresh);
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)refresh();});
  window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);});
  window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;refresh();}});
  refresh();
})();
