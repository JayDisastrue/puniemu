namespace Puniemu.Src.Server.Admin
{
    public static class AdminPage
    {
        public const string Html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Puniemu admin</title>
<style>
  :root { color-scheme: light dark; --bg:#f4f5f7; --card:#fff; --ink:#1c1e21; --mute:#667085; --line:#d9dce1; --accent:#c8102e; --ok:#18794e; }
  @media (prefers-color-scheme: dark) { :root { --bg:#15171a; --card:#1f2226; --ink:#eceef1; --mute:#98a2b3; --line:#343840; --accent:#ff5a6e; --ok:#4cc38a; } }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--ink); }
  main { max-width:900px; margin:0 auto; padding:16px; display:grid; gap:16px; }
  h1 { font-size:20px; margin:8px 0 0; }
  h2 { font-size:15px; margin:0 0 10px; }
  section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
  .row { display:flex; flex-wrap:wrap; gap:8px; align-items:end; }
  label { display:grid; gap:4px; font-size:12px; color:var(--mute); flex:1 1 150px; }
  input { font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:7px; background:transparent; color:inherit; min-width:0; width:100%; }
  button { font:inherit; padding:8px 14px; border:1px solid var(--line); border-radius:7px; background:transparent; color:inherit; cursor:pointer; white-space:nowrap; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button:disabled { opacity:.5; cursor:default; }
  #accounts { max-height:260px; overflow:auto; margin-top:10px; border:1px solid var(--line); border-radius:7px; }
  .acc { display:flex; justify-content:space-between; gap:12px; padding:8px 10px; border-bottom:1px solid var(--line); cursor:pointer; }
  .acc:last-child { border-bottom:0; }
  .acc[aria-selected=true] { outline:2px solid var(--accent); outline-offset:-2px; }
  .acc small, .mute { color:var(--mute); }
  #status { min-height:1.4em; font-size:13px; }
  #status.ok { color:var(--ok); } #status.err { color:var(--accent); }
  [hidden] { display:none !important; }
  .stack { display:grid; gap:14px; }
</style>
</head>
<body>
<main>
  <h1>Puniemu admin</h1>

  <section id="loginBox">
    <h2>Admin password</h2>
    <form class="row" id="loginForm">
      <label>Password<input type="password" id="password" autocomplete="current-password" required></label>
      <button class="primary">Unlock</button>
    </form>
  </section>

  <div id="panel" class="stack" hidden>
    <section>
      <h2>Accounts</h2>
      <form class="row" id="searchForm">
        <label>Search by player name or friend code<input id="search" placeholder="Leave empty for the most recent 200"></label>
        <button>Search</button>
      </form>
      <div id="accounts"></div>
    </section>

    <section id="editor" hidden>
      <h2 id="who"></h2>
      <p class="mute" id="summary"></p>
      <div class="stack">
        <form class="row" id="currencyForm">
          <label>Y-Money<input type="number" id="ymoney" min="0" max="99999999"></label>
          <label>Spirit (paid)<input type="number" id="hitodama" min="0" max="99999999"></label>
          <button class="primary">Set</button>
        </form>
        <form class="row" id="yokaiForm">
          <label>Yo-kai (name or ID)<input id="yokai" list="yokaiList" autocomplete="off"></label>
          <button class="primary" value="give">Give</button>
          <button value="max">Give maxed</button>
        </form>
        <div class="row">
          <button id="allYokai">Give every Yo-kai</button>
          <button id="allYokaiMax">Give every Yo-kai, maxed</button>
        </div>
        <form class="row" id="itemForm">
          <label>Item (name or ID)<input id="item" list="itemList" autocomplete="off"></label>
          <label style="flex:0 1 110px">Count<input type="number" id="itemCount" value="1" min="1" max="9999"></label>
          <button class="primary">Give</button>
        </form>
      </div>
      <p class="mute">Restart the game on that device after a change so the client reloads the save.</p>
    </section>

    <div id="status" role="status"></div>
  </div>
  <datalist id="yokaiList"></datalist>
  <datalist id="itemList"></datalist>
</main>
<script>
const $ = id => document.getElementById(id);
let password = sessionStorage.getItem('adminPassword') || '';
let selected = null;

async function api(path, body) {
  const res = await fetch('/admin/api/' + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'X-Admin-Password': password, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await res.json().catch(() => ({ error: 'Server error (' + res.status + ').' }));
  if (!res.ok) throw new Error(data.error || 'Server error (' + res.status + ').');
  return data;
}
function say(text, ok) { $('status').textContent = text; $('status').className = ok ? 'ok' : 'err'; }
async function act(label, fn) {
  say(label + '...', true);
  document.querySelectorAll('#editor button').forEach(b => b.disabled = true);
  try { const r = await fn(); say(label + ': done.', true); return r; }
  catch (e) { say(e.message, false); }
  finally { document.querySelectorAll('#editor button').forEach(b => b.disabled = false); }
}
function idFrom(value) { const m = /(\d+)\s*$/.exec(value.trim()); return m ? Number(m[1]) : null; }

function showAccount(a) {
  selected = a.gdkey;
  $('editor').hidden = false;
  $('who').textContent = (a.playerName || '(no name)') + '  ·  ' + (a.characterId || '');
  $('summary').textContent = 'Y-Money ' + a.ymoney + ' · spirit ' + a.hitodama + ' paid + ' + a.freeHitodama + ' free · ' + a.yokaiCount + ' Yo-kai';
  $('ymoney').value = a.ymoney; $('hitodama').value = a.hitodama;
}
async function loadAccounts() {
  const list = await api('accounts?q=' + encodeURIComponent($('search').value.trim()));
  const box = $('accounts'); box.replaceChildren();
  if (!list.length) { box.textContent = 'No accounts found.'; return; }
  for (const a of list) {
    const row = document.createElement('div'); row.className = 'acc'; row.tabIndex = 0;
    const name = document.createElement('span'); name.textContent = a.playerName || '(character not created)';
    const meta = document.createElement('small'); meta.textContent = (a.characterId || '') + (a.lastLogin ? ' · ' + a.lastLogin : '');
    row.append(name, meta);
    const pick = async () => {
      try {
        showAccount(await api('account', { gdkey: a.gdkey }));
        box.querySelectorAll('.acc').forEach(r => r.setAttribute('aria-selected', r === row));
        say('', true);
      } catch (e) { say(e.message, false); }
    };
    row.onclick = pick; row.onkeydown = e => { if (e.key === 'Enter') pick(); };
    box.append(row);
  }
}
async function unlock() {
  const catalog = await api('catalog');
  for (const [listId, rows] of [['yokaiList', catalog.yokai], ['itemList', catalog.items]]) {
    const frag = document.createDocumentFragment();
    for (const r of rows) { const o = document.createElement('option'); o.value = r.name + ' ' + r.id; frag.append(o); }
    $(listId).replaceChildren(frag);
  }
  sessionStorage.setItem('adminPassword', password);
  $('loginBox').hidden = true; $('panel').hidden = false;
  await loadAccounts();
}
$('loginForm').onsubmit = async e => {
  e.preventDefault(); password = $('password').value;
  try { await unlock(); } catch (err) { alert(err.message); }
};
$('searchForm').onsubmit = e => { e.preventDefault(); loadAccounts().catch(err => say(err.message, false)); };
$('currencyForm').onsubmit = async e => {
  e.preventDefault();
  const a = await act('Set currency', () => api('currency', { gdkey: selected, ymoney: Number($('ymoney').value), hitodama: Number($('hitodama').value) }));
  if (a) showAccount(a);
};
$('yokaiForm').onsubmit = async e => {
  e.preventDefault();
  const id = idFrom($('yokai').value);
  if (id === null) return say('Pick a Yo-kai from the list or type its ID.', false);
  const a = await act('Give Yo-kai ' + id, () => api('yokai', { gdkey: selected, youkaiId: id, max: e.submitter.value === 'max' }));
  if (a) showAccount(a);
};
for (const [btn, max] of [['allYokai', false], ['allYokaiMax', true]]) {
  $(btn).onclick = async () => {
    if (!confirm('Give every Yo-kai in the game to this account? This cannot be undone from the panel.')) return;
    const a = await act('Give every Yo-kai', () => api('yokai/all', { gdkey: selected, max }));
    if (a) showAccount(a);
  };
}
$('itemForm').onsubmit = async e => {
  e.preventDefault();
  const id = idFrom($('item').value);
  if (id === null) return say('Pick an item from the list or type its ID.', false);
  await act('Give item ' + id, () => api('item', { gdkey: selected, itemId: id, count: Number($('itemCount').value) }));
};
if (password) unlock().catch(() => { password = ''; sessionStorage.removeItem('adminPassword'); });
</script>
</body>
</html>
""";
    }
}
