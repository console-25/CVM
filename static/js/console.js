(() => {
  'use strict';
  const root = document.getElementById('console-workspace'); if (!root) return;
  const id = Number(root.dataset.consoleId), byId = name => document.getElementById(`console-${name}`);
  const login = byId('login'), form = byId('form'), connect = byId('connect'), user = byId('user'), pass = byId('password');
  const auth=byId('auth'),privateKey=byId('private-key');
  auth.addEventListener('change',()=>{const key=auth.value==='key';byId('key-fields').hidden=!key;privateKey.required=key;pass.required=!key;pass.value='';privateKey.value='';byId('password-label').textContent=key?'Key passphrase (if encrypted)':'VPS password';pass.placeholder=key?'Optional passphrase':'Enter current password';});
  let state = 'idle', endpoint = null, attempt = '', socket, term, fit, timer, disposed = false, preparing = false;
  function error(text) { byId('error').textContent = text; byId('error').hidden = !text; }
  function setState(next, message) {
    state = next; byId('state').dataset.state = next;
    byId('state').textContent = ({idle:'Not connected',connecting:'Connecting',connected:'Connected',offline:'Panel offline'})[next] || 'Disconnected';
    byId('message').textContent = message || byId('state').textContent;
    connect.disabled = next === 'connecting' || preparing || !endpoint || !socket?.connected;
    byId('disconnect').disabled = next !== 'connected' && next !== 'connecting';
    form.setAttribute('aria-busy', String(next === 'connecting'));
    user.disabled = pass.disabled = privateKey.disabled = auth.disabled = next === 'connecting';
  }
  function refit() { try { fit?.fit(); byId('dimensions').textContent = `${term.cols} × ${term.rows}`; if (state === 'connected') socket.emit('ssh_resize',{vps_id:id, cols:term.cols, rows:term.rows}); } catch {} }
  async function prepare() {
    if (preparing || state === 'connecting' || state === 'connected') return;
    preparing = true; endpoint = null; error(''); setState('idle','Preparing SSH endpoint');
    byId('endpoint').textContent = 'Preparing SSH endpoint…';
    try {
      const response = await fetch(`/vps/${id}/console/connect`, {method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},signal:AbortSignal.timeout(45000)});
      const data = await response.json(); if (!response.ok || !data.success) throw Error(data.error || 'Could not prepare SSH.');
      endpoint = data.connection; byId('endpoint').textContent = `${endpoint.host}:${endpoint.port} → guest SSH`;
    } catch (e) { error(e.message || 'Could not reach the panel.'); byId('endpoint').textContent = 'Endpoint unavailable'; }
    finally { preparing = false; setState(socket?.connected ? 'idle':'offline', endpoint ? 'Ready · enter your credentials' : 'Refresh connection details to retry'); }
  }
  function stop(message='Disconnected') {
    clearTimeout(timer); attempt = ''; socket?.emit('ssh_disconnect',{vps_id:id});
    login.hidden = false; setState('idle',message); pass.value = ''; privateKey.value = '';
  }
  if (root.dataset.sshAvailable !== 'true' || typeof Terminal === 'undefined' || typeof io === 'undefined' || typeof FitAddon === 'undefined') {
    byId('endpoint').textContent = 'Console unavailable'; error('Console dependencies could not load. Check the panel SSH dependencies and access to its terminal assets.'); return;
  }
  term = new Terminal({cursorBlink:true,fontFamily:'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',fontSize:13,lineHeight:1.35,scrollback:5000,theme:{background:'#081221',foreground:'#dce3f5',cursor:'#62b6ff',selectionBackground:'#3478f640',black:'#21283a',red:'#f48894',green:'#8cdbb9',yellow:'#e7c68c',blue:'#99b9f1',magenta:'#c5adfa',cyan:'#91cdd1',white:'#dce3f5'}});
  fit = new FitAddon.FitAddon(); term.loadAddon(fit); term.open(document.getElementById('terminal'));
  socket = io(window.location.origin, {path:'/socket.io',transports:['polling','websocket'],timeout:15000});
  const matches = data => data && data.attempt_id === attempt && attempt !== '' && (!data.vps_id || data.vps_id === id);
  socket.on('connect', () => { setState('idle',endpoint?'Ready · enter your credentials':'Preparing SSH endpoint'); });
  socket.on('connect_error', () => { clearTimeout(timer); login.hidden = false; attempt = ''; error('Cannot reach the console transport. Check your connection and proxy configuration.'); setState('offline'); });
  socket.on('disconnect', () => { clearTimeout(timer); attempt = ''; pass.value = ''; privateKey.value = '';  login.hidden = false; error('Connection to the panel was lost. Once it reconnects, sign in again.'); setState('offline'); });
  socket.on('ssh_connected', data => { if (!matches(data)) return; clearTimeout(timer); pass.value = ''; privateKey.value = '';  error(''); login.hidden = true; setState('connected',`${data.username}@${data.host}:${data.port}`); refit(); term.focus(); });
  socket.on('ssh_output', data => { if (matches(data)) term.write(data.data); });
  socket.on('ssh_error', data => { if (!matches(data)) return; clearTimeout(timer); login.hidden = false; setState('idle','Connection failed · check the message above');pass.value='';privateKey.value=''; error(data.error || 'Could not connect.'); pass.focus(); });
  socket.on('ssh_disconnected', data => { if (!matches(data)) return; clearTimeout(timer); login.hidden = false; setState('idle','SSH session ended'); pass.value = ''; privateKey.value = '';  });
  form.addEventListener('submit', e => {
    e.preventDefault(); if (state === 'connecting' || state === 'connected') return;
    if (!endpoint || !socket.connected) { error('Wait for the panel connection, then refresh the connection details.'); return; }
    if (!user.value.trim() || (auth.value==='key'?!privateKey.value:!pass.value)) { error('Enter your current VPS username and password.'); return; }
    error(''); term.reset(); attempt = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    setState('connecting','Authenticating with the guest SSH service');
    socket.emit('ssh_connect', {vps_id:id,attempt_id:attempt,username:user.value.trim(),password:pass.value,...(auth.value==='key'?{private_key:privateKey.value}:{}),cols:term.cols,rows:term.rows});
    timer = setTimeout(() => { stop('Connection timed out'); error('SSH did not respond in time. Check the guest SSH service and try again.'); },45000);
  });
  term.onData(data => { if (state === 'connected') socket.emit('ssh_input',{vps_id:id,input:data}); });
  term.onResize(({cols,rows}) => { byId('dimensions').textContent = `${cols} × ${rows}`; if (state === 'connected') socket.emit('ssh_resize',{vps_id:id,cols,rows}); });
  byId('retry').addEventListener('click', prepare);
  byId('disconnect').addEventListener('click', () => stop());
  byId('clear').addEventListener('click', () => { term.clear(); if (state === 'connected') term.focus(); });
  byId('show-password').addEventListener('click', () => { const show = pass.type === 'password'; pass.type = show?'text':'password'; byId('show-password').setAttribute('aria-pressed',String(show)); byId('show-password').setAttribute('aria-label',show?'Hide password':'Show password'); });
  byId('fullscreen').addEventListener('click', async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await root.querySelector('.terminal-shell').requestFullscreen(); refit(); } catch { error('Fullscreen is unavailable in this browser.'); } });
  document.addEventListener('fullscreenchange',refit);
  const observer = new ResizeObserver(() => { if (!disposed) requestAnimationFrame(refit); }); observer.observe(document.getElementById('terminal'));
  window.addEventListener('pagehide', () => { disposed = true; clearTimeout(timer); observer.disconnect(); socket.emit('ssh_disconnect',{vps_id:id}); socket.disconnect(); term.dispose(); });
  refit(); prepare();
})();
