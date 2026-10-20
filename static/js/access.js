(() => {
  'use strict';
  const dialog = document.getElementById('access-dialog'); if (!dialog) return;
  const get = name => dialog.querySelector(`[data-${name}]`);
  const vpsId = Number(dialog.dataset.accessVps);
  let job = null, timer = null, busy = false, generation = 0;
  const method = () => dialog.querySelector('input[name="access-method"]:checked').value;
  function error(text) { get('access-error').textContent = text; get('access-error').hidden = !text; }
  function choices() {
    const relay = method() !== 'shared_ipv4';
    get('install-option').hidden = !relay; get('relay-note').hidden = !relay;
    get('method-description').textContent = relay ? 'Create a temporary shell session through the selected relay. The VPS must have outbound Internet access.' : 'Creates or reuses a TCP forward to guest port 22. Use your current VPS username and password.';
  }
  dialog.querySelectorAll('[name="access-method"]').forEach(input => input.addEventListener('change', choices));
  async function request(url, options={}) {
    const response = await fetch(url, {headers:{'Content-Type':'application/json',Accept:'application/json'}, signal:AbortSignal.timeout(45000), ...options});
    let data; try { data = await response.json(); } catch { throw Error('The panel returned an unreadable response. Check your connection and retry.'); }
    if (!response.ok || !data.success) throw Error(data.error || 'Could not prepare access.'); return data;
  }
  function reset() { busy = false; get('access-setup').hidden = false; get('access-progress').hidden = true; get('access-generate').hidden = false; get('access-generate').disabled = false; }
  function render(current) {
    job = current;
    if (current.state === 'preparing') { get('access-message').textContent = current.message; get('access-end').hidden = false; return; }
    busy = false; get('access-progress').hidden = true;
    if (current.state !== 'ready') {
      reset(); get('access-end').hidden = current.state === 'ended'; error(current.message || 'Session expired. Generate a new one.'); return;
    }
    get('access-result').hidden = false; get('access-generate').hidden = true; get('access-end').hidden = false;
    get('access-end').textContent = current.method === 'shared_ipv4' ? 'Back to methods' : 'End session';
    const result = current.result || {};
    get('command-result').hidden = !result.ssh_command; document.getElementById('access-command').value = result.ssh_command || '';
    // Backend validates relay hosts; validate again before exposing an external link.
    let link = '';
    try { const url = new URL(result.web_url); if (url.protocol === 'https:' && !url.username && !url.password && (url.hostname === 'sshx.io' || url.hostname === 'tmate.io' || url.hostname.endsWith('.tmate.io'))) link = url.href; } catch {}
    document.getElementById('access-link').value = link;
    get('link-result').hidden = !link; get('open-session').hidden = !link;
    if (link) get('open-session').href = link; else get('open-session').removeAttribute('href');
    get('access-result-note').textContent = current.method === 'shared_ipv4' ? 'The port mapping remains available under Ports. The guest SSH service must be running and the host port allowed through the firewall.' : `Keep this link private. Session expires ${new Date(current.expires_at * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}.`;
  }
  async function poll(token) {
    if (!job || token !== generation || !dialog.open) return;
    try { const data = await request(`/vps/${vpsId}/access/${job.id}`); if (token !== generation) return; render(data.job); if (data.job.state === 'preparing' && dialog.open) timer = setTimeout(() => poll(token), 1500); }
    catch (e) { if (token !== generation) return; busy = false; get('access-progress').hidden = true; error(e.message + ' Reopen this dialog to check the session again.'); }
  }
  get('access-generate').addEventListener('click', async () => {
    if (busy) return; busy = true; const token = ++generation; clearTimeout(timer); error('');
    get('access-generate').disabled = true; get('access-setup').hidden = true; get('access-result').hidden = true; get('access-progress').hidden = false; get('access-message').textContent = 'Checking your VPS…';
    try { const data = await request(`/vps/${vpsId}/ssh`, {method:'POST',body:JSON.stringify({method:method(),install_tools:get('install-tools').checked})}); if (token !== generation) return; render(data.job); if (data.job.state === 'preparing' && dialog.open) timer = setTimeout(() => poll(token), 1000); }
    catch (e) { if (token !== generation) return; reset(); error(e.message); }
  });
  get('access-end').addEventListener('click', async () => {
    if (!job) return; get('access-end').disabled = true;
    try { await request(`/vps/${vpsId}/access/${job.id}`, {method:'DELETE'}); generation++; clearTimeout(timer); job = null; get('access-result').hidden = true; get('access-end').hidden = true; get('access-end').textContent = 'End session'; reset(); error(''); }
    catch (e) { error(e.message); }
    finally { get('access-end').disabled = false; }
  });
  get('copy-command').addEventListener('click', () => workspaceCopy(document.getElementById('access-command').value));
  get('copy-link').addEventListener('click', () => workspaceCopy(document.getElementById('access-link').value));
  function close() { clearTimeout(timer); dialog.close(); }
  get('access-close').addEventListener('click', close); dialog.addEventListener('cancel', () => clearTimeout(timer));
  window.HVMAccess = { open() { if (!dialog.open) dialog.showModal(); choices(); if (job) { clearTimeout(timer); poll(generation); } } };
  document.querySelectorAll('[data-access-open]').forEach(button => button.addEventListener('click', HVMAccess.open));
  choices();
})();
