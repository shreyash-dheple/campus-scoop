const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stars = n => '★'.repeat(Math.round(n)) + '☆'.repeat(5 - Math.round(n));

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Something went wrong. Try again.');
  return data;
}

/* ---------- live clock (India time, synced with the server) ---------- */
let offset = 0, sessionsRef = [], lastSig = '', rerender = () => {}, onSigChange = () => {};
const setClock = ts => { offset = ts - Date.now(); };
const nowMin = () => ((Date.now() + offset + 330 * 60000) % 86400000) / 60000;
const clockStr = () => new Date(Date.now() + offset).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit' });
const statusOf = (s, m = nowMin()) => m >= s.start && m < s.end ? 'live' : m >= s.end ? 'ended' : 'upcoming';
const sig = ss => ss.map(s => statusOf(s)).join();
const fmtDur = mins => { mins = Math.max(1, Math.ceil(mins)); const h = Math.floor(mins / 60), m = mins % 60; return h ? `${h}h ${m}m` : `${m}m`; };

setInterval(() => {
  if (!sessionsRef.length) return;
  const s = sig(sessionsRef);
  if (s !== lastSig) { lastSig = s; onSigChange(); }
  rerender();
}, 10000);

/* ---------- Home ---------- */
function homeBanner(ss) {
  const m = nowMin();
  const live = ss.find(s => statusOf(s, m) === 'live');
  const next = ss.find(s => statusOf(s, m) === 'upcoming');
  let body, cls = '', bar = '';
  if (live) {
    cls = 'live';
    body = `<b><span class="pulse"></span>${live.icon} ${live.name} (${live.hint}) is live</b><span class="muted">Ends ${live.end_label}, ${fmtDur(live.end - m)} left</span>`;
    bar = `<div class="prog"><i style="width:${((m - live.start) / (live.end - live.start)) * 100}%"></i></div>`;
  } else if (next) {
    body = `<b>No meal session right now</b><span class="muted">${next.icon} ${next.name} (${next.hint}) starts at ${next.start_label}, in ${fmtDur(next.start - m)}</span>`;
  } else {
    cls = 'ended';
    body = `<b>Today's sessions have ended</b><span class="muted">${ss[0].name} starts again at ${ss[0].start_label}</span>`;
  }
  return `<div class="nowcard ${cls}"><div class="nowtop"><div>${body}</div><div class="clock">${clockStr()}</div></div>${bar}</div>`;
}

async function loadList() {
  try {
    const messes = await api('/messes');
    $('#list').innerHTML = messes.map(m => `
      <a class="card" href="mess.html?id=${m.id}">
        <div><b>${esc(m.name)}</b><span class="muted">${esc(m.area)}</span><br>
          <span class="tag ${m.menu_now ? '' : 'off'}">${!m.session_name ? 'Closed right now' : m.menu_now ? `${esc(m.session_name)} menu posted` : `No ${esc(m.session_name.toLowerCase())} menu yet`}</span></div>
        <div class="score">${m.review_count ? `<strong>${m.avg_rating.toFixed(1)}</strong><div class="stars">${stars(m.avg_rating)}</div><span class="muted">${m.review_count} reviews</span>` : '<span class="muted">No reviews yet</span>'}</div>
      </a>`).join('') || '<p class="muted">No messes yet.</p>';
  } catch (e) { $('#list').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function initHome() {
  const clock = await api('/now');
  setClock(clock.now_ts); sessionsRef = clock.sessions; lastSig = sig(sessionsRef);
  rerender = () => { $('#now').innerHTML = homeBanner(sessionsRef); };
  onSigChange = loadList;
  rerender(); loadList();
}

/* ---------- Mess page ---------- */
let messId, picked = 0, session = null, data = null, demo = false;
const dayLabel = d => d === data.today ? 'Today' : new Date(d + 'T00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' });

async function loadMess() {
  data = await api('/messes/' + messId + (session ? '?session=' + session : ''));
  session = data.session; demo = data.demo;
  setClock(data.now_ts); sessionsRef = data.sessions; lastSig = sig(sessionsRef);
  render();
}

function render() {
  if (!data) return;
  const m = data, ss = m.sessions, s = ss.find(t => t.key === session);
  const now = nowMin(), st = statusOf(s, now), open = st === 'live' || demo, n = s.name.toLowerCase();

  document.title = m.name + ' · CampusScoop';
  $('#name').textContent = m.name;
  $('#meta').textContent = m.area + (m.review_count ? `, ${m.avg_rating.toFixed(1)} ★ overall (${m.review_count})` : '');

  $('#tabs').innerHTML = ss.map(t => {
    const ts = statusOf(t, now);
    const sub = ts === 'live' ? '● Live' : ts === 'ended' ? 'Ended' : `Starts ${t.start_label}`;
    return `<button data-key="${t.key}" class="${t.key === session ? 'on' : ''}" aria-pressed="${t.key === session}"><b>${t.icon} ${t.name}</b><small>${t.hint}</small><small class="st ${ts}">${sub}</small></button>`;
  }).join('');

  let body, bar = '';
  if (st === 'live') {
    body = `<b><span class="pulse"></span>${s.name} is live</b><span class="muted">Ends ${s.end_label}, ${fmtDur(s.end - now)} left</span>`;
    bar = `<div class="prog"><i style="width:${((now - s.start) / (s.end - s.start)) * 100}%"></i></div>`;
  } else if (st === 'upcoming') {
    body = `<b>${s.name} hasn't started</b><span class="muted">Starts at ${s.start_label}, in ${fmtDur(s.start - now)}. Posting opens then.</span>`;
  } else {
    body = `<b>${s.name} has ended</b><span class="muted">Ended at ${s.end_label}. Posting is closed for this session.</span>`;
  }
  if (demo && st !== 'live') body += `<span class="muted">Demo mode: posting is open for every session.</span>`;
  $('#strip').innerHTML = `<div class="nowcard ${st === 'live' ? 'live' : st === 'ended' ? 'ended' : ''}"><div class="nowtop"><div>${body}</div><div class="clock">${clockStr()}</div></div>${bar}</div>`;

  $('#menuTitle').textContent = `${s.name} menu`;
  $('#menuBtn').hidden = !open;
  $('#menu').innerHTML = m.menu
    ? `${esc(m.menu.items)}<div class="muted">Posted by ${esc(m.menu.nickname)}</div>${m.menu.mine ? `<button class="link" data-menu="${m.menu.id}">Delete my menu</button>` : ''}`
    : `<span class="muted">${st === 'live' ? `No one has posted what's being served yet. Be the first.`
        : st === 'ended' ? `No one posted a menu for today's ${esc(n)} session.`
        : `The ${esc(n)} session starts at ${s.start_label}. The menu will show up here once someone posts it.`}</span>`;

  $('#revTitle').textContent = `${s.name} reviews` + (m.reviews.length ? `, ${m.session_avg.toFixed(1)} ★ this week` : '');
  $('#reviews').innerHTML = m.reviews.map(r => `
    <div class="review">
      <div class="who"><span>${esc(r.nickname)}, ${esc(dayLabel(r.day))}</span><span class="stars">${stars(r.rating)}</span></div>
      ${r.comment ? `<p>${esc(r.comment)}</p>` : ''}
      ${r.mine
        ? `<span class="muted">👍 ${r.votes}</span> <button class="vote del" data-del="${r.id}">Delete my review</button>`
        : `<button class="vote ${r.voted ? 'done' : ''}" data-id="${r.id}">👍 Helpful · ${r.votes}</button>`}
    </div>`).join('') || `<p class="muted">${st === 'live' ? 'No reviews yet. Rate it to start.'
        : st === 'ended' ? `No one has reviewed the ${esc(n)} session this week.`
        : `No ${esc(n)} reviews yet. Reviews open when it starts at ${s.start_label}.`}</p>`;

  const rb = $('#rateBtn');
  rb.disabled = !open;
  rb.textContent = open ? `★ Rate the ${n}` : st === 'upcoming' ? `Rating opens at ${s.start_label}` : `${s.name} has ended, rating is closed`;
}

function initMess() {
  messId = new URLSearchParams(location.search).get('id');
  if (!messId) { location.href = 'index.html'; return; }
  rerender = render;
  loadMess().catch(e => toast(e.message));
  const name = () => data.sessions.find(t => t.key === session).name.toLowerCase();

  const sp = $('#starPick');
  sp.innerHTML = [1,2,3,4,5].map(n => `<button type="button" data-n="${n}" role="radio" aria-label="${n} star">★</button>`).join('');
  sp.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    picked = +b.dataset.n;
    sp.querySelectorAll('button').forEach(x => x.classList.toggle('on', +x.dataset.n <= picked));
  });

  $('#tabs').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    session = b.dataset.key; loadMess().catch(err => toast(err.message));
  };
  $('#rateBtn').onclick = () => { $('#rateTitle').textContent = `Rate the ${name()}`; $('#rateDlg').showModal(); };
  $('#menuBtn').onclick = () => { $('#menuDlgTitle').textContent = `What's being served in the ${name()}?`; $('#menuDlg').showModal(); };
  document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => b.closest('dialog').close());

  $('#rateSend').onclick = async () => {
    if (!picked) return toast('Pick a star rating first');
    try {
      await api(`/messes/${messId}/reviews`, { method: 'POST', body: JSON.stringify({ rating: picked, comment: $('#comment').value.trim(), session }) });
      $('#rateDlg').close(); $('#comment').value = ''; picked = 0;
      sp.querySelectorAll('button').forEach(x => x.classList.remove('on'));
      toast('Review posted'); loadMess();
    } catch (e) { toast(e.message); }
  };

  $('#menuSend').onclick = async () => {
    const items = $('#items').value.trim();
    if (!items) return toast("Type what's being served first");
    try {
      await api(`/messes/${messId}/menu`, { method: 'POST', body: JSON.stringify({ items, session }) });
      $('#menuDlg').close(); $('#items').value = '';
      toast('Menu posted'); loadMess();
    } catch (e) { toast(e.message); }
  };

  $('#reviews').addEventListener('click', async e => {
    const d = e.target.closest('[data-del]');
    if (d) {
      if (!confirm('Delete your review?')) return;
      try { await api('/reviews/' + d.dataset.del, { method: 'DELETE' }); toast('Review deleted'); loadMess(); }
      catch (err) { toast(err.message); }
      return;
    }
    const b = e.target.closest('.vote'); if (!b) return;
    try { await api(`/reviews/${b.dataset.id}/vote`, { method: 'POST' }); loadMess(); }
    catch (err) { toast(err.message); }
  });

  $('#menu').addEventListener('click', async e => {
    const d = e.target.closest('[data-menu]'); if (!d) return;
    if (!confirm('Delete your menu post?')) return;
    try { await api('/menus/' + d.dataset.menu, { method: 'DELETE' }); toast('Menu deleted'); loadMess(); }
    catch (err) { toast(err.message); }
  });
}

document.body.dataset.page === 'home' ? initHome() : initMess();