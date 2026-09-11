import html

from flask import Response

MANAGED_PANEL_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>__GAME__ · Save Sync</title><style>
:root{color-scheme:dark;font-family:system-ui;background:#10141b;color:#eef2f8}*{box-sizing:border-box}body{max-width:1180px;margin:2rem auto;padding:0 1rem}header,.card{background:#19212d;border:1px solid #344154;border-radius:14px;padding:1.2rem;margin:1rem 0}.grid,.forms{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.8rem}.label,.hint{color:#9eabc0;font-size:.85rem}.value{font-size:1.05rem;overflow-wrap:anywhere}button,a.button{background:#5b7cfa;color:white;border:0;border-radius:8px;padding:.62rem .85rem;text-decoration:none;cursor:pointer}button.secondary{background:#344154}button.danger{background:#9d3f4a}button:disabled{opacity:.5;cursor:not-allowed}input,select{width:100%;background:#101722;color:#eef2f8;border:1px solid #44536a;border-radius:8px;padding:.65rem}fieldset{border:1px solid #344154;border-radius:10px;padding:.8rem}legend{color:#c8d4e8;padding:0 .35rem}.busy,.backup-pending,.backup-warning{color:#ffbf69}.free,.backup-completed,.enabled{color:#72dfa1}.backup-failed,.backup-unknown,.disabled{color:#ff7b86}.backup-disabled,.backup-not_initialized{color:#9eabc0}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:.55rem;border-bottom:1px solid #344154;vertical-align:top}code{font-size:.78rem}.actions{display:flex;gap:.35rem;flex-wrap:wrap}.actions button{padding:.38rem .55rem}.badge{display:inline-block;border:1px solid #44536a;border-radius:99px;padding:.12rem .45rem;font-size:.78rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#101722;border:1px solid #344154;border-radius:8px;padding:.7rem}.section-head{display:flex;justify-content:space-between;align-items:center;gap:.7rem;flex-wrap:wrap}h3{margin-top:1.5rem}
</style></head><body>
<header><h1>__GAME__ synchronization</h1><div>User: __USER__ · Role: __ROLE__</div></header>
<section class="card"><h2 id="state">Loading…</h2><div class="grid" id="facts"></div><p id="lock"></p><a class="button" href="__WEB_API_PREFIX__/download">Download latest version</a> <button id="force" hidden>Force unlock</button></section>
<section class="card"><h2>External backup</h2><div class="grid" id="backupFacts"></div><p id="backupConfig">Loading…</p><p id="backupState">Loading…</p></section>
<section class="card"><h2>History</h2><div class="table-wrap"><table><thead><tr><th>Version</th><th>__IDENTITY_LABEL__</th><th>User</th><th class="managed-only" hidden>Computer</th><th>Date</th><th>Size</th><th>SHA-256</th><th>Actions</th></tr></thead><tbody id="history"></tbody></table></div></section>
<section class="card" id="tokensCard" hidden><h2>Tokens API</h2><p>The new token is shown only once.</p><input id="tokenUser" placeholder="Authorized user"><input id="legacyTokenName" placeholder="Computer name"><button id="createLegacyToken">Create token</button><pre id="legacyNewToken"></pre><div id="legacyTokens"></div></section>
<section class="card" id="accessCard" hidden>
 <div class="section-head"><div><h2>Access & computers</h2><p class="hint">Authentik proves identity; Save Sync controls who may use this game and which computers may host it. Creating a user here authorizes an existing Authentik username; it does not create an Authentik account.</p></div></div>
 <div class="forms">
  <fieldset><legend>Add user</legend><input id="newUsername" placeholder="Authentik username"><input id="newDisplayName" placeholder="Display name"><input id="newSlot" placeholder="Retention slot"><select id="newRole"><option value="player">Player</option><option value="admin">Admin</option></select><button id="createUser">Add user</button></fieldset>
  <fieldset><legend>Add computer</legend><select id="hostUser"></select><input id="hostClientId" placeholder="ClientId, e.g. alex-pc"><input id="hostName" placeholder="Computer name"><button id="createHost">Add computer</button></fieldset>
  <fieldset><legend>Create computer token</legend><select id="tokenHost"></select><input id="hostTokenName" placeholder="Token label"><button id="createToken">Create token</button><p class="hint">Computer tokens can synchronize saves but cannot perform admin operations, even when their owner is an admin.</p></fieldset>
 </div>
 <pre id="newToken" hidden></pre>
 <h3>Users</h3><div class="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Computers</th><th>Last seen</th><th>Actions</th></tr></thead><tbody id="users"></tbody></table></div>
 <h3>Computers</h3><div class="table-wrap"><table><thead><tr><th>Owner</th><th>Computer</th><th>ClientId</th><th>Status</th><th>Tokens</th><th>Last seen</th><th>Last publish</th><th>Actions</th></tr></thead><tbody id="hosts"></tbody></table></div>
 <h3>API tokens</h3><p class="hint">Legacy unbound tokens remain visible for migration/administration. New sync tokens must be bound to a registered computer.</p><div id="tokens"></div>
 <h3>Recent audit</h3><div class="table-wrap"><table><thead><tr><th>When</th><th>User</th><th>Computer</th><th>Event</th><th>Result</th></tr></thead><tbody id="audit"></tbody></table></div>
</section>
<script>
const csrf='__CSRF__',role='__ROLE__',managedHosts=__MANAGED_HOSTS__;
const headers={'X-CSRF-Token':csrf,'Content-Type':'application/json'};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeInt=value=>Number.isSafeInteger(Number(value))?Number(value):0;
const fmt=value=>value||'—';
let accessState={users:[],hosts:[],tokens:[],audit:[]};
async function mutate(url,method='POST',body={}){const r=await fetch(url,{method,headers,body:method==='DELETE'?undefined:JSON.stringify(body)});const j=await r.json();if(!r.ok)alert(j.message||'Error');return [r,j]}
async function load(){
 const backup=fetch('__WEB_API_PREFIX__/backup-status').then(async r=>r.ok?await r.json():null).catch(()=>null);
 const [s,h,b]=await Promise.all([fetch('__WEB_API_PREFIX__/status').then(r=>r.json()),fetch('__WEB_API_PREFIX__/history').then(r=>r.json()),backup]);
 document.querySelector('#state').textContent=s.locked?'Status: in use':'Status: available';document.querySelector('#state').className=s.locked?'busy':'free';
 const factRows=[['Version',s.version],['__IDENTITY_LABEL__',s.saveIdentity||'—'],['Last update',s.updatedAt||'Not initialized'],['Last player',s.updatedBy||'—'],...(managedHosts?[['Last computer',s.updatedHostName||s.updatedClientId||'—']]:[]),['Size',s.size+' bytes'],['SHA-256',s.sha256||'—']];
 document.querySelector('#facts').innerHTML=factRows.map(x=>`<div><div class=label>${esc(x[0])}</div><div class=value>${esc(x[1])}</div></div>`).join('');
 document.querySelector('#lock').textContent=s.locked?(managedHosts?`Server in use by ${s.lock.owner}${s.lock.hostName?` on ${s.lock.hostName}`:''} (${s.lock.clientId||'legacy client'}). Last heartbeat: ${s.lock.lastHeartbeatAt}. Expires: ${s.lock.expiresAt}.`:`Server in use by ${s.lock.owner}. Last heartbeat: ${s.lock.lastHeartbeatAt}. Expires: ${s.lock.expiresAt}.`):'';
 if(b){
  const labels={completed:'Completed',pending:'Pending',failed:'Failed',unknown:'No result',disabled:'Disabled',not_initialized:'No save'};
  const stateLabel=b.stalePending&&b.state==='unknown'?'No result (stale marker)':labels[b.state]||b.state;
  document.querySelector('#backupConfig').textContent=`Automatic backup: ${b.enabled?'enabled':'disabled ⚠'}`;document.querySelector('#backupConfig').className=b.enabled?'backup-completed':'backup-warning';
  document.querySelector('#backupState').textContent=`Current version backup state: ${stateLabel}`;document.querySelector('#backupState').className=`backup-${b.state}`;
  const pendingVersions=Array.isArray(b.pendingVersions)?b.pendingVersions:[];
  const staleVersions=Array.isArray(b.stalePendingVersions)?b.stalePendingVersions:[];
  document.querySelector('#backupFacts').innerHTML=[['Latest published version',b.latestPublishedVersion||'—'],['Latest backed-up version',b.lastCompleted?.version||'—'],['Latest completed backup',b.lastCompleted?.completedAt||'—'],['Latest exitCode',b.lastAttempt?.exitCode??'—'],['Pending',pendingVersions.map(x=>x.version).join(', ')||'None'],['Stale markers',staleVersions.map(x=>x.version).join(', ')||'None'],['Current version backed up',b.latestVersionBackedUp?'Yes':'No']].map(x=>`<div><div class=label>${esc(x[0])}</div><div class=value>${esc(x[1])}</div></div>`).join('');
 }else{
  document.querySelector('#backupConfig').textContent='Automatic backup: unavailable';document.querySelector('#backupConfig').className='backup-unknown';
  document.querySelector('#backupState').textContent='Current version backup state: unavailable';document.querySelector('#backupState').className='backup-unknown';document.querySelector('#backupFacts').innerHTML='';
 }
 document.querySelector('#history').innerHTML=h.versions.map(v=>{const id=safeInt(v.version);return `<tr><td>${id}</td><td><code>${esc(v.saveIdentity)}</code></td><td>${esc(v.updatedBy)}</td>${managedHosts?`<td class=managed-only>${esc(v.hostName||v.clientId||'—')}</td>`:''}<td>${esc(v.updatedAt)}</td><td>${esc(v.size)}</td><td><code>${esc(v.sha256)}</code></td><td>${role==='admin'?`<div class=actions><a href=__WEB_API_PREFIX__/history/${id}/download>Download</a><button onclick=restoreV(${id})>Restore</button></div>`:''}</td></tr>`}).join('');
 document.querySelectorAll('.managed-only').forEach(el=>el.hidden=!managedHosts);
 document.querySelector('#force').hidden=role!=='admin'||!s.locked;if(role==='admin'){if(managedHosts)await loadAccess();else await loadTokens()}
}
async function restoreV(v){if(confirm(`Restore v${v} as a new version?`)){await mutate(`__WEB_API_PREFIX__/history/${v}/restore`);load()}}
document.querySelector('#force').onclick=async()=>{const reason=prompt('Reason for force unlock:');if(reason){await mutate('__WEB_API_PREFIX__/admin/force-unlock','POST',{reason});load()}};
async function loadAccess(){
 document.querySelector('#accessCard').hidden=false;
 const [u,h,t,a]=await Promise.all([fetch('__WEB_API_PREFIX__/admin/users').then(r=>r.json()),fetch('__WEB_API_PREFIX__/admin/hosts').then(r=>r.json()),fetch('__WEB_API_PREFIX__/admin/tokens').then(r=>r.json()),fetch('__WEB_API_PREFIX__/admin/audit?limit=50').then(r=>r.json())]);
 accessState={users:u.users||[],hosts:h.hosts||[],tokens:t.tokens||[],audit:a.events||[]};
 document.querySelector('#users').innerHTML=accessState.users.map(u=>{const id=safeInt(u.id);return `<tr><td><strong>${esc(u.displayName)}</strong><br><span class=hint>${esc(u.username)} · slot ${esc(u.slot)}</span></td><td><span class=badge>${esc(u.role)}</span></td><td class=${u.active?'enabled':'disabled'}>${u.active?'Enabled':'Disabled'}</td><td>${esc(`${u.activeHostCount}/${u.hostCount}`)}</td><td>${esc(fmt(u.lastSeenAt))}</td><td><div class=actions><button class=secondary onclick=editUser(${id})>Edit</button><button class=secondary onclick=toggleUserRole(${id},'${u.role}')>${u.role==='admin'?'Make player':'Make admin'}</button><button class=${u.active?'danger':'secondary'} onclick=toggleUser(${id},${u.active})>${u.active?'Disable':'Enable'}</button></div></td></tr>`}).join('');
 document.querySelector('#hosts').innerHTML=accessState.hosts.map(h=>{const id=safeInt(h.id);const active=h.active&&h.userActive;return `<tr><td>${esc(h.displayName)}<br><span class=hint>${esc(h.username)}</span></td><td>${esc(h.name)}${h.sessionActive?' <span class="badge busy">IN USE</span>':''}</td><td><code>${esc(h.clientId)}</code></td><td class=${active?'enabled':'disabled'}>${active?'Enabled':h.userActive?'Disabled':'User disabled'}</td><td>${esc(h.activeTokenCount)}</td><td>${esc(fmt(h.lastSeenAt))}</td><td>${esc(fmt(h.lastPublishedAt))}</td><td><div class=actions><button class=secondary onclick=editHost(${id})>Rename</button><a href="__WEB_API_PREFIX__/admin/hosts/${id}/client-config">Config</a><button class=${h.active?'danger':'secondary'} onclick=toggleHost(${id},${h.active})>${h.active?'Disable':'Enable'}</button></div></td></tr>`}).join('');
 document.querySelector('#tokens').innerHTML=accessState.tokens.map(t=>{const id=safeInt(t.id);const binding=t.host_id?`${esc(t.host_name)} · <code>${esc(t.client_id)}</code>`:'<span class="hint">Legacy / unbound</span>';return `<p>#${id} ${esc(t.username)} · ${esc(t.name)} · ${binding} · ${t.revoked_at?'revoked':`<button onclick=revokeT(${id})>Revoke</button>`}</p>`}).join('')||'<p class=hint>No API tokens.</p>';
 document.querySelector('#audit').innerHTML=accessState.audit.map(a=>`<tr><td>${esc(a.at)}</td><td>${esc(a.username||'system')}</td><td>${esc(a.client_id||'—')}</td><td>${esc(a.event)}</td><td class=${a.success?'enabled':'disabled'}>${a.success?'OK':'Failed'}</td></tr>`).join('')||'<tr><td colspan=5 class=hint>No audit events.</td></tr>';
 const activeUsers=accessState.users.filter(u=>u.active);document.querySelector('#hostUser').innerHTML=activeUsers.map(u=>`<option value=${safeInt(u.id)}>${esc(u.displayName)} (${esc(u.username)})</option>`).join('');
 const tokenHosts=accessState.hosts.filter(h=>h.active&&h.userActive);document.querySelector('#tokenHost').innerHTML=tokenHosts.map(h=>`<option value=${safeInt(h.id)}>${esc(h.displayName)} · ${esc(h.name)} · ${esc(h.clientId)}</option>`).join('');
}
document.querySelector('#createUser').onclick=async()=>{const body={username:newUsername.value.trim(),displayName:newDisplayName.value.trim(),slot:newSlot.value.trim(),role:newRole.value};const [r]=await mutate('__WEB_API_PREFIX__/admin/users','POST',body);if(r.ok){newUsername.value='';newDisplayName.value='';newSlot.value='';await loadAccess()}};
document.querySelector('#createHost').onclick=async()=>{const body={userId:safeInt(hostUser.value),clientId:hostClientId.value.trim(),name:hostName.value.trim()};const [r]=await mutate('__WEB_API_PREFIX__/admin/hosts','POST',body);if(r.ok){hostClientId.value='';hostName.value='';await loadAccess()}};
document.querySelector('#createToken').onclick=async()=>{const host=accessState.hosts.find(h=>safeInt(h.id)===safeInt(tokenHost.value));if(!host){alert('Select an enabled computer first.');return}const [r,j]=await mutate('__WEB_API_PREFIX__/admin/tokens','POST',{username:host.username,hostId:host.id,name:hostTokenName.value.trim()});if(r.ok){newToken.hidden=false;newToken.textContent=`Copy this token now; it will not be shown again:\n${j.token}`;hostTokenName.value='';await loadAccess()}};
async function editUser(id){const u=accessState.users.find(x=>safeInt(x.id)===safeInt(id));if(!u)return;const displayName=prompt('Display name:',u.displayName);if(displayName===null)return;const slot=prompt('Retention slot:',u.slot);if(slot===null)return;const [r]=await mutate(`__WEB_API_PREFIX__/admin/users/${safeInt(id)}`,'PATCH',{displayName,slot});if(r.ok)loadAccess()}
async function toggleUserRole(id,current){if(current==='admin'&&!confirm('Change this administrator to player?'))return;const [r]=await mutate(`__WEB_API_PREFIX__/admin/users/${safeInt(id)}`,'PATCH',{role:current==='admin'?'player':'admin'});if(r.ok)loadAccess()}
async function toggleUser(id,current){if(current&&!confirm('Disable this user? Their API access will stop; an active lock is deliberately kept until expiry unless you force-unlock it.'))return;const [r]=await mutate(`__WEB_API_PREFIX__/admin/users/${safeInt(id)}`,'PATCH',{active:!current});if(r.ok)loadAccess()}
async function editHost(id){const h=accessState.hosts.find(x=>safeInt(x.id)===safeInt(id));if(!h)return;const name=prompt('Computer name:',h.name);if(name===null)return;const [r]=await mutate(`__WEB_API_PREFIX__/admin/hosts/${safeInt(id)}`,'PATCH',{name});if(r.ok)loadAccess()}
async function toggleHost(id,current){if(current&&!confirm('Disable this computer? Its token will stop working. An active lock is deliberately kept until expiry unless you force-unlock it.'))return;const [r]=await mutate(`__WEB_API_PREFIX__/admin/hosts/${safeInt(id)}`,'PATCH',{active:!current});if(r.ok)loadAccess()}
async function revokeT(id){if(!confirm('Revoke this token?'))return;const [r]=await mutate(`__WEB_API_PREFIX__/admin/tokens/${safeInt(id)}`,'DELETE');if(r.ok)loadAccess()}
async function loadTokens(){document.querySelector('#tokensCard').hidden=false;const j=await fetch('__WEB_API_PREFIX__/admin/tokens').then(r=>r.json());document.querySelector('#legacyTokens').innerHTML=j.tokens.map(t=>{const id=safeInt(t.id);return `<p>#${id} ${esc(t.username)} · ${esc(t.name)} · ${t.revoked_at?'revoked':`<button onclick=revokeLegacyT(${id})>Revoke</button>`}</p>`}).join('')}
async function revokeLegacyT(id){const [r]=await mutate(`__WEB_API_PREFIX__/admin/tokens/${safeInt(id)}`,'DELETE');if(r.ok)loadTokens()}
document.querySelector('#createLegacyToken').onclick=async()=>{const [r,j]=await mutate('__WEB_API_PREFIX__/admin/tokens','POST',{username:tokenUser.value,name:legacyTokenName.value});if(r.ok){legacyNewToken.textContent=j.token;loadTokens()}};
load();setInterval(load,30000)
</script></body></html>"""


def register_panel_routes(
    *,
    app,
    connect,
    web_auth,
    csrf_value,
    game_key,
    display_game,
    identity_label,
    managed_hosts,
    legacy_palworld,
):
    def panel():
        db = connect()
        try:
            user, web_failure = web_auth(db)
        finally:
            db.close()
        if web_failure == "web_user_not_allowed":
            return Response(
                f"User not authorized for {display_game}",
                403,
                content_type="text/plain; charset=utf-8",
            )
        if not user:
            return Response(
                "Authentication required",
                401,
                content_type="text/plain; charset=utf-8",
            )
        csrf = csrf_value(user["username"]) or ""
        panel_template = MANAGED_PANEL_HTML if managed_hosts else PANEL_HTML
        panel_html = (
            panel_template.replace("__USER__", html.escape(user["username"], quote=True))
            .replace("__ROLE__", user["role"])
            .replace("__CSRF__", csrf)
            .replace("__GAME__", html.escape(display_game, quote=True))
            .replace("__IDENTITY_LABEL__", html.escape(identity_label, quote=True))
            .replace("__WEB_API_PREFIX__", f"/games/{game_key}/api")
            .replace("__MANAGED_HOSTS__", "true" if managed_hosts else "false")
        )
        return Response(panel_html, content_type="text/html; charset=utf-8")

    app.add_url_rule(f"/games/{game_key}", "game_panel", panel, methods=["GET"])
    app.add_url_rule(
        f"/games/{game_key}/", "game_panel_slash", panel, methods=["GET"]
    )
    if legacy_palworld:
        app.add_url_rule("/palworld", "palworld_panel", panel, methods=["GET"])
        app.add_url_rule(
            "/palworld/", "palworld_panel_slash", panel, methods=["GET"]
        )


# Keep the unmanaged panel byte-for-byte equivalent in structure and behavior to
# the pre-managed-host UI. Palworld deliberately uses this template so enabling
# managed computers for experimental games does not change its stable panel.
PANEL_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>__GAME__ · Save Sync</title><style>
:root{color-scheme:dark;font-family:system-ui;background:#10141b;color:#eef2f8}body{max-width:980px;margin:3rem auto;padding:0 1rem}header,.card{background:#19212d;border:1px solid #344154;border-radius:14px;padding:1.2rem;margin:1rem 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.8rem}.label{color:#9eabc0;font-size:.85rem}.value{font-size:1.1rem;overflow-wrap:anywhere}button,a.button{background:#5b7cfa;color:white;border:0;border-radius:8px;padding:.7rem 1rem;text-decoration:none;cursor:pointer}.busy,.backup-pending,.backup-warning{color:#ffbf69}.free,.backup-completed{color:#72dfa1}.backup-failed,.backup-unknown{color:#ff7b86}.backup-disabled,.backup-not_initialized{color:#9eabc0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:.55rem;border-bottom:1px solid #344154}code{font-size:.78rem}</style></head><body>
<header><h1>__GAME__ synchronization</h1><div>User: __USER__ · Role: __ROLE__</div></header><section class="card"><h2 id="state">Loading…</h2><div class="grid" id="facts"></div><p id="lock"></p><a class="button" href="__WEB_API_PREFIX__/download">Download latest version</a> <button id="force" hidden>Force unlock</button></section><section class="card"><h2>External backup</h2><div class="grid" id="backupFacts"></div><p id="backupConfig">Loading…</p><p id="backupState">Loading…</p></section><section class="card"><h2>History</h2><table><thead><tr><th>Version</th><th>__IDENTITY_LABEL__</th><th>User</th><th>Date</th><th>Size</th><th>SHA-256</th><th>Actions</th></tr></thead><tbody id="history"></tbody></table></section><section class="card" id="tokensCard" hidden><h2>Tokens API</h2><p>The new token is shown only once.</p><input id="tokenUser" placeholder="Authorized user"><input id="tokenName" placeholder="Computer name"><button id="createToken">Create token</button><pre id="newToken"></pre><div id="tokens"></div></section>
<script>
const csrf='__CSRF__',role='__ROLE__';
const headers={'X-CSRF-Token':csrf,'Content-Type':'application/json'};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeInt=value=>Number.isSafeInteger(Number(value))?Number(value):0;
async function mutate(url,method='POST',body={}){const r=await fetch(url,{method,headers,body:method==='DELETE'?undefined:JSON.stringify(body)});const j=await r.json();if(!r.ok)alert(j.message||'Error');return [r,j]}
async function load(){
 const backup=fetch('__WEB_API_PREFIX__/backup-status').then(async r=>r.ok?await r.json():null).catch(()=>null);
 const [s,h,b]=await Promise.all([fetch('__WEB_API_PREFIX__/status').then(r=>r.json()),fetch('__WEB_API_PREFIX__/history').then(r=>r.json()),backup]);
 document.querySelector('#state').textContent=s.locked?'Status: in use':'Status: available';document.querySelector('#state').className=s.locked?'busy':'free';
 document.querySelector('#facts').innerHTML=[['Version',s.version],['__IDENTITY_LABEL__',s.saveIdentity||'—'],['Last update',s.updatedAt||'Not initialized'],['Last player',s.updatedBy||'—'],['Size',s.size+' bytes'],['SHA-256',s.sha256||'—']].map(x=>`<div><div class=label>${esc(x[0])}</div><div class=value>${esc(x[1])}</div></div>`).join('');
 document.querySelector('#lock').textContent=s.locked?`Server in use by ${s.lock.owner}. Last heartbeat: ${s.lock.lastHeartbeatAt}. Expires: ${s.lock.expiresAt}.`:'';
 if(b){
  const labels={completed:'Completed',pending:'Pending',failed:'Failed',unknown:'No result',disabled:'Disabled',not_initialized:'No save'};
  const stateLabel=b.stalePending&&b.state==='unknown'?'No result (stale marker)':labels[b.state]||b.state;
  document.querySelector('#backupConfig').textContent=`Automatic backup: ${b.enabled?'enabled':'disabled ⚠'}`;document.querySelector('#backupConfig').className=b.enabled?'backup-completed':'backup-warning';
  document.querySelector('#backupState').textContent=`Current version backup state: ${stateLabel}`;document.querySelector('#backupState').className=`backup-${b.state}`;
  const pendingVersions=Array.isArray(b.pendingVersions)?b.pendingVersions:[];
  const staleVersions=Array.isArray(b.stalePendingVersions)?b.stalePendingVersions:[];
  document.querySelector('#backupFacts').innerHTML=[['Latest published version',b.latestPublishedVersion||'—'],['Latest backed-up version',b.lastCompleted?.version||'—'],['Latest completed backup',b.lastCompleted?.completedAt||'—'],['Latest exitCode',b.lastAttempt?.exitCode??'—'],['Pending',pendingVersions.map(x=>x.version).join(', ')||'None'],['Stale markers',staleVersions.map(x=>x.version).join(', ')||'None'],['Current version backed up',b.latestVersionBackedUp?'Yes':'No']].map(x=>`<div><div class=label>${esc(x[0])}</div><div class=value>${esc(x[1])}</div></div>`).join('');
 }else{
  document.querySelector('#backupConfig').textContent='Automatic backup: unavailable';document.querySelector('#backupConfig').className='backup-unknown';
  document.querySelector('#backupState').textContent='Current version backup state: unavailable';document.querySelector('#backupState').className='backup-unknown';document.querySelector('#backupFacts').innerHTML='';
 }
 document.querySelector('#history').innerHTML=h.versions.map(v=>{const id=safeInt(v.version);return `<tr><td>${id}</td><td><code>${esc(v.saveIdentity)}</code></td><td>${esc(v.updatedBy)}</td><td>${esc(v.updatedAt)}</td><td>${esc(v.size)}</td><td><code>${esc(v.sha256)}</code></td><td>${role==='admin'?`<a href=__WEB_API_PREFIX__/history/${id}/download>Download</a> <button onclick=restoreV(${id})>Restore</button>`:''}</td></tr>`}).join('');
 document.querySelector('#force').hidden=role!=='admin'||!s.locked;if(role==='admin')loadTokens()
}
async function restoreV(v){if(confirm(`Restore v${v} as a new version?`)){await mutate(`__WEB_API_PREFIX__/history/${v}/restore`);load()}}
document.querySelector('#force').onclick=async()=>{const reason=prompt('Reason for force unlock:');if(reason){await mutate('__WEB_API_PREFIX__/admin/force-unlock','POST',{reason});load()}};
async function loadTokens(){document.querySelector('#tokensCard').hidden=false;const j=await fetch('__WEB_API_PREFIX__/admin/tokens').then(r=>r.json());document.querySelector('#tokens').innerHTML=j.tokens.map(t=>{const id=safeInt(t.id);return `<p>#${id} ${esc(t.username)} · ${esc(t.name)} · ${t.revoked_at?'revoked':`<button onclick=revokeT(${id})>Revoke</button>`}</p>`}).join('')}
async function revokeT(id){await mutate(`__WEB_API_PREFIX__/admin/tokens/${id}`,'DELETE');loadTokens()}
document.querySelector('#createToken').onclick=async()=>{const [r,j]=await mutate('__WEB_API_PREFIX__/admin/tokens','POST',{username:tokenUser.value,name:tokenName.value});if(r.ok){newToken.textContent=j.token;loadTokens()}};
load();setInterval(load,30000)
</script></body></html>"""
