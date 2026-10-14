// app.js —— 画台（一页到底）
//
// 按用户反馈改的（2026-10-12）：
//   "切工程不显示对话、也没输入框，还要先点一下物料，太复杂了"
// ⇒ ① 输入框**常驻底部**，任何时候都看得见
//    ② 选中工程就**自动打开最近那一单**，对话直接出来，不用先点物料
//    ③ 物料横向一条（chips），点一下才切换，不点也不挡路
//
// 两条老规矩不变：
//   · 界面不自己编状态：内容都来自内核
//   · 点下去立刻有反馈：我的话先上屏 → "它在想…" → 最后用**账**重画一遍

const $ = (id) => document.getElementById(id);

let projects = [];
let currentProject = null;
let currentOrder = null;
let orders = [];
let busy = false;

// ---- 出图预览的状态（2026-10-13 加：版本对比 / 九宫格 / 放大窗）----
let versions = [];        // 这一单的版本列表（来自账 history[]）
let images = {};          // ver -> {data_url, sha, name} 或 {err}
let cmp = [];             // 当前选中的版本（1 个=单张，2 个=并排；顺序=点的顺序）
let gridOn = false;       // 图上是否画 9 格格号
const zState = { ver: 0, list: [], scale: 0, x: 0, y: 0, natW: 1, natH: 1 };

// ---------------------------------------------------------------- 错误条
function showErr(reply, what) {
  const bar = $('errBar');
  const parts = [`${what}失败`];
  if (reply && reply.error) parts.push(`原因：${reply.error}`);
  if (reply && reply.detail) parts.push(`细节：${reply.detail}`);
  if (reply && reply.status) parts.push(`（状态码 ${reply.status}）`);
  bar.textContent = parts.join('\n');
  bar.classList.remove('hidden');
}

function clearErr() {
  const bar = $('errBar');
  bar.textContent = '';
  bar.classList.add('hidden');
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// ---------------------------------------------------------------- 内核状态
async function loadKernelStatus() {
  try {
    const st = await window.go.main.App.KernelStatus();
    const badge = $('kernelBadge');
    if (st.running) { badge.textContent = `内核：运行中（PID ${st.pid}）`; badge.className = 'badge ok'; }
    else if (st.root) { badge.textContent = '内核：就绪（待首次调用）'; badge.className = 'badge'; }
    else { badge.textContent = '内核：异常'; badge.className = 'badge bad'; showErr({ error: '找不到项目根', detail: st.lastErr }, '内核定位'); }
  } catch (e) {
    $('kernelBadge').textContent = '内核：调用失败';
    $('kernelBadge').className = 'badge bad';
  }
}

// ---------------------------------------------------------------- 工程
async function loadProjects() {
  const r = await window.go.main.App.Projects();
  if (!r.ok) { showErr(r, '读工程列表'); return; }
  projects = (r.result && r.result.projects) || [];
  renderProjects();
}

function renderProjects() {
  const ul = $('projects');
  ul.innerHTML = '';
  if (!projects.length) { ul.innerHTML = '<li class="empty">还没有工程</li>'; return; }
  for (const p of projects) {
    const li = document.createElement('li');
    if (currentProject && p.id === currentProject.id) li.className = 'active';
    li.innerHTML = `<span class="nm" title="${escapeHtml(p['显示名'] || p.id)}">${escapeHtml(p['显示名'] || p.id)}</span>
                    <span class="ct">${p.order_count} 单</span>`;
    li.addEventListener('click', () => selectProject(p));
    ul.appendChild(li);
  }
}

async function createProject() {
  const input = $('newName');
  const name = (input.value || '').trim();
  clearErr();
  if (!name) { showErr({ error: '工程名不能为空', detail: '先取个名字，再点新建' }, '新建工程'); input.focus(); return; }
  const btn = $('btnNew');
  btn.disabled = true; btn.textContent = '新建中…';
  try {
    const r = await window.go.main.App.NewProject(name);
    if (!r.ok) { showErr(r, `新建「${name}」`); return; }
    input.value = '';
    await loadProjects();
    const created = r.result && r.result.project;
    const found = projects.find((p) => p.id === (created && created['工程目录名']));
    if (found) await selectProject(found);
  } catch (e) {
    showErr({ error: '调 NewProject 抛异常', detail: String(e) }, '新建工程');
  } finally {
    btn.disabled = false; btn.textContent = '新建';
  }
}

// ---------------------------------------------------------------- 选工程 ⇒ 自动打开最近一单
async function selectProject(p, wantOrder) {
  currentProject = p;
  currentOrder = wantOrder || null;
  renderProjects();
  $('crumb').textContent = p['显示名'] || p.id;
  clearErr();
  await loadOrders(wantOrder);          // 里面会**自动打开最近那一单**
  updateComposer();
}

async function loadOrders(wantOrder) {
  if (!currentProject) return;
  const r = await window.go.main.App.Orders(currentProject.id);
  if (!r.ok) { showErr(r, '读单列表'); return; }
  orders = (r.result && r.result.orders) || [];   // 内核已按最近更新倒序
  $('meta').textContent = `目录名 ${currentProject.id}`;
  renderChips();

  // ★ 自动打开：优先用户指定的单（回到上次），否则最近更新那一单 —— 不用先去点物料
  const pick = wantOrder && orders.some((o) => o.order_id === wantOrder) ? wantOrder : (orders[0] && orders[0].order_id);
  if (orders.length && (!currentOrder || !orders.some((o) => o.order_id === currentOrder))) {
    currentOrder = pick || null;
    renderChips();
  }
  if (!orders.length) currentOrder = null;
  await refreshOrder();
}

function renderChips() {
  const box = $('orders');
  box.innerHTML = '';
  if (!orders.length) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  for (const o of orders) {
    const b = document.createElement('button');
    b.className = 'chip' + (o.order_id === currentOrder ? ' on' : '');
    b.textContent = `${o.src_name || o.order_id}${o.n_ver ? '（' + o.n_ver + ' 版）' : ''}`;
    b.title = o.order_id;
    b.addEventListener('click', () => openOrder(o.order_id));
    box.appendChild(b);
  }
}

async function openOrder(oid) {
  currentOrder = oid;
  renderChips();
  updateComposer();
  await refreshOrder();
}

async function refreshOrder() {
  const box = $('chat');
  cmp = [];                    // 换单 ⇒ 重新选版本（默认回到"看最新"）
  versions = [];
  regionPreviewCache = {};
  closeZoom();
  $('preview').classList.add('hidden');       // 先藏，等确认有产物再显示
  if (!currentOrder) {
    box.innerHTML = currentProject
      ? '<div class="msg system"><div class="who">系统</div><div class="txt">这个工程还没有单 —— 点右上角「＋ 投料（选一张图）」选一张图，我就建一单，然后小助手会先猜你要做什么。</div></div>'
      : '<div class="msg system"><div class="who">系统</div><div class="txt">左边先选一个工程（没有就新建一个）。</div></div>';
    return;
  }
  const r = await window.go.main.App.OrderDetail(currentProject.id, currentOrder);
  if (!r.ok) { showErr(r, '读这一单'); return; }
  const d = r.result;
  const ord = d['订单'] || {};
  $('meta').textContent = `目录名 ${currentProject.id} ｜ ${ord.n_ver || 0} 版 ｜ 产物 ${(d['产物'] || []).length} 个`;
  renderChat(d['流水'] || [], d['流水坏行'] || 0);
  await refreshPreview(ord);
}

// ★ 出图之后，最新一版要在这儿看得见（图 + 指标 + 上机档名）
//
// 2026-10-13 改（用户点名 ①②）：
//   ① 两次出图都要能看见、方便对比 ⇒ **版本条**：每版一个钮，点两版就并排（顺序=点的顺序）
//   ② 大窗口预览 ⇒ 点「放大」进放大窗：滚轮缩放、拖动平移、1:1、上一版/下一版
//   ＋ 九宫格标签：图上画 0~8 的格号（可开关）——用户说"第 4 格"，小助手读的是同一格
//
// 两条老规矩不变：
//   · 界面**不自己编数**：格号、指标、sha 全来自账（`history[]` 与 order.image 的回执）
//   · 缺数据**不许炸**：加这两项之前出的版本没有 zones/png_sha256，缺就写"无"

const ZONE_NOTE = '格号：0 左上 ・ 1 上中 ・ 2 右上 ・ 3 左中 ・ 4 正中 ・ 5 右中 ・ 6 左下 ・ 7 下中 ・ 8 右下';

async function refreshPreview(ord) {
  images = {};
  versions = (ord.history || []).map((h) => ({
    ver: h.ver,
    name: h.img ? String(h.img).split(/[\\/]/).pop() : '',
    sha: h.png_sha256 || '',            // 加这一项之前出的版本没有 ⇒ 空串，显示"无"
    zones: h.zones || null,             // 同上
    metrics: h.metrics || {},
    knobs: h.knobs || {},
    local: h.local_ops || [],
    note: h.note || '',
  })).filter((v) => v.ver > 0);
  if (!versions.length) { $('preview').classList.add('hidden'); return; }
  if (!cmp.length) cmp = [versions[versions.length - 1].ver];   // 默认看最新那一版（旧行为不变）
  $('preview').classList.remove('hidden');
  renderBar();
  await renderPanes();
}

function renderBar() {
  const bar = $('pvBar');
  bar.innerHTML = '';
  const cmpOn = cmp.length === 2;
  if (versions.length > 1) {
    const hint = document.createElement('span');
    hint.className = 'pv-hint';
    hint.textContent = cmpOn ? '并排：' : (versions.length > 1 ? '点两版并排 →' : '');
    if (!cmpOn) bar.appendChild(hint);
  }
  for (const v of versions) {
    const i = cmp.indexOf(v.ver);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'vchip' + (i >= 0 ? ' on' : '') + (i === 0 ? ' left' : '') + (i === 1 ? ' right' : '');
    const z = (v.zones && v.zones[4]) || {};
    b.innerHTML = `<span class="vv">v${v.ver}</span>` +
      `<span class="vm">墨点 ${v.metrics.ink_pct != null ? v.metrics.ink_pct : '?'}%</span>` +
      `<span class="vm">暗部 ${v.metrics.dark_pct != null ? v.metrics.dark_pct : '?'}%</span>` +
      (v.sha ? `<span class="vs" title="与账里记的同一张（png sha256）">${escapeHtml(v.sha.slice(0, 8))}</span>` : '<span class="vs">无 sha</span>');
    b.title = `第 ${v.ver} 版${v.note ? '｜' + v.note : ''}｜正中格墨点 ${z.ink_pct != null ? z.ink_pct : '?'}%`;
    b.addEventListener('click', () => toggleVer(v.ver));
    bar.appendChild(b);
  }
  const reset = document.createElement('button');
  reset.type = 'button';
  reset.className = 'mini';
  reset.textContent = '看最新';
  reset.title = '回到"只看最新一版"';
  reset.addEventListener('click', () => { cmp = [versions[versions.length - 1].ver]; renderBar(); renderPanes(); });
  bar.appendChild(reset);
}

function toggleVer(ver) {
  const i = cmp.indexOf(ver);
  if (i >= 0 && cmp.length > 1) cmp.splice(i, 1);          // 再点一次取消
  else if (i < 0) cmp = cmp.length >= 2 ? [cmp[1], ver] : [...cmp, ver];   // 只留两版
  renderBar();
  renderPanes();
}

async function loadVersion(ver) {
  if (images[ver]) return images[ver];
  images[ver] = { pending: true };
  try {
    const r = await window.go.main.App.OrderImage(currentProject.id, currentOrder, 'png', ver);
    images[ver] = r && r.ok
      ? { data_url: (r.result || {}).data_url, sha: (r.result || {}).sha256, name: (r.result || {}).名字 }
      // ★ 取图失败**不许静默**：以前这里直接 return，界面上什么都不会说
      : { err: (r && (r.error || r.detail)) || '取图失败' };
  } catch (e) {
    images[ver] = { err: String(e) };
  }
  return images[ver];
}

async function renderPanes() {
  const box = $('pvPanes');
  box.innerHTML = '';
  const list = cmp.length ? [...cmp] : [versions[versions.length - 1].ver];
  box.classList.toggle('many', list.length > 1);
  for (const ver of list) {
    const v = versions.find((x) => x.ver === ver);
    if (!v) continue;
    const pane = document.createElement('div');
    pane.className = 'pane';
    pane.innerHTML =
      `<div class="pane-head"><span class="pane-ver">第 ${v.ver} 版</span>` +
      `<span class="note">${v.name ? escapeHtml(v.name) : ''}</span></div>` +
      `<div class="pane-img"><div class="ph note">取图中…</div></div>` +
      `<div class="pane-cap note"></div>`;
    const cap = pane.querySelector('.pane-cap');
    cap.textContent =
      `${(v.metrics && v.metrics.ink_pct != null) ? '墨点 ' + v.metrics.ink_pct + '%' : '墨点 ?'}` +
      ` ・ 暗部 ${v.metrics.dark_pct != null ? v.metrics.dark_pct : '?'}%` +
      ` ・ 亮部 ${v.metrics.light_pct != null ? v.metrics.light_pct : '?'}%\n` +
      `${v.knobs && Object.keys(v.knobs).length ? '旋钮 ' + Object.entries(v.knobs).filter(([, x]) => x).map(([k, x]) => k + '=' + x).join('、') : '旋钮 全默认'}` +
      `${v.local && v.local.length ? '｜局部 ' + JSON.stringify(v.local) : ''}\n` +
      `png sha256 ${v.sha ? v.sha.slice(0, 16) + '…' : '账里没记（加这功能之前出的版本）'}`;
    cap.title = v.sha ? '完整 sha256：' + v.sha : '账里没记这一版的 png sha256';
    box.appendChild(pane);

    const slot = pane.querySelector('.pane-img');
    const im = await loadVersion(ver);
    slot.innerHTML = '';
    if (im.err) {
      const e = document.createElement('div');
      e.className = 'pane-err';
      e.textContent = '这一版取不到图：' + im.err;
      slot.appendChild(e);
      continue;
    }
    const img = document.createElement('img');
    img.src = im.data_url;
    img.alt = `第 ${v.ver} 版预览`;
    img.title = '点一下放大看（滚轮缩放 / 拖动平移）';
    img.addEventListener('click', () => openZoom(ver, false));
    slot.appendChild(img);
    if (gridOn) slot.appendChild(buildGrid());
  }
  $('pvMeta').textContent = gridOn ? ZONE_NOTE : '';
}

function buildGrid(scale) {
  const g = document.createElement('div');
  g.className = 'grid-layer';
  const k = scale && scale > 0 ? 1 / scale : 1;
  g.dataset.k = String(k);
  for (let i = 0; i < 9; i++) {
    const c = document.createElement('div');
    c.className = 'gcell';
    const num = document.createElement('span');
    num.className = 'gnum';
    num.style.transform = `scale(${k})`;
    num.style.transformOrigin = 'left top';
    num.textContent = String(i);
    c.appendChild(num);
    g.appendChild(c);
  }
  return g;
}

function fillZoomGrid() {
  const box = $('zoomGrid');
  box.innerHTML = '';
  if (!gridOn) return;
  box.style.width = zState.natW + 'px';
  box.style.height = zState.natH + 'px';
  box.appendChild(buildGrid(zState.scale));
}

// ---------------------------------------------------------------- 放大窗口
function openZoom(ver, grid) {
  const list = cmp.length ? [...cmp] : [versions[versions.length - 1].ver];
  zState.ver = ver;
  zState.list = list;
  zState.scale = 0;
  zState.x = 0;
  zState.y = 0;
  if (grid !== undefined) gridOn = grid;
  $('zoom').classList.remove('hidden');
  showZoom();
}

async function showZoom() {
  const v = versions.find((x) => x.ver === zState.ver);
  $('zoomTitle').textContent = v ? `第 ${v.ver} 版${v.name ? '　' + v.name : ''}` : '放大看';
  $('zoomCap').textContent = v
    ? `墨点 ${v.metrics.ink_pct != null ? v.metrics.ink_pct : '?'}% ・ 暗部 ${v.metrics.dark_pct != null ? v.metrics.dark_pct : '?'}% ・ 亮部 ${v.metrics.light_pct != null ? v.metrics.light_pct : '?'}%\n` +
      `png sha256 ${v.sha || '账里没记'}\n滚轮缩放 ・ 拖动平移 ・ 空格切格号 ・ ←/→ 换版本 ・ Esc 关闭`
    : '';
  $('zoomGrid').classList.toggle('hidden', !gridOn);
  const im = await loadVersion(zState.ver);
  const img = $('zoomImg');
  if (im.err) {
    img.removeAttribute('src');
    $('zoomCap').textContent = '这一版取不到图：' + im.err;
    return;
  }
  if (img.src !== im.data_url) img.src = im.data_url;
  const apply = () => {
    zState.natW = img.naturalWidth || 1;
    zState.natH = img.naturalHeight || 1;
    if (!zState.scale) fitZoom();
    else applyZoom();
  };
  if (img.complete && img.naturalWidth) apply();
  else img.onload = apply;
}

function fitZoom() {
  const stage = $('zoomStage');
  const pad = 34;
  zState.scale = Math.min((stage.clientWidth - pad) / zState.natW, (stage.clientHeight - pad) / zState.natH, 1);
  zState.x = 0; zState.y = 0;
  applyZoom();
}

function clampPan() {
  const stage = $('zoomStage');
  const halfW = Math.max(0, (zState.natW * zState.scale - stage.clientWidth) / 2);
  const halfH = Math.max(0, (zState.natH * zState.scale - stage.clientHeight) / 2);
  zState.x = Math.max(-halfW, Math.min(halfW, zState.x));
  zState.y = Math.max(-halfH, Math.min(halfH, zState.y));
}

function applyZoom() {
  clampPan();
  $('zoomInner').style.transform =
    `translate(-50%, -50%) translate(${zState.x}px, ${zState.y}px) scale(${zState.scale})`;
  $('zoomPct').textContent = Math.round(zState.scale * 100) + '%';
  // 格号要反向缩放才不被一起放大；比例变了才重建（拖动平移时不重建）
  if (gridOn) {
    const cur = $('zoomGrid').querySelector('.grid-layer');
    const want = zState.scale > 0 ? 1 / zState.scale : 1;
    if (!cur || Math.abs((parseFloat(cur.dataset.k) || 1) - want) > want * 0.01) fillZoomGrid();
  }
}

function zoomStep(mult, cx, cy) {
  const stage = $('zoomStage');
  const rect = stage.getBoundingClientRect();
  const mx = (cx == null ? rect.width / 2 : cx - rect.left) - rect.width / 2;
  const my = (cy == null ? rect.height / 2 : cy - rect.top) - rect.height / 2;
  const old = zState.scale;
  const next = Math.max(0.15, Math.min(8, old * mult));
  if (next === old) return;
  zState.x = mx - (mx - zState.x) * (next / old);
  zState.y = my - (my - zState.y) * (next / old);
  zState.scale = next;
  applyZoom();
}

function closeZoom() {
  $('zoom').classList.add('hidden');
}

function zoomStepVer(d) {
  if (zState.list.length < 2) return;
  const i = zState.list.indexOf(zState.ver);
  zState.ver = zState.list[(i + d + zState.list.length) % zState.list.length];
  zState.scale = 0; zState.x = 0; zState.y = 0;
  showZoom();
}


const KIND_LABEL = { material: '料', user: '你', assistant: '小助手', action: '动作', system: '系统' };

// ★ 位置确认卡（2026-10-13）：小助手说"我理解的是左边一列" ⇒ 把那一块裁出来给它看，认了才动手。
//   为什么不画九宫格格号：用户明确否掉了（"太机械了"）。他只看这一块像不像。
let regionPreviewCache = {};

async function previewRegion(key) {
  if (regionPreviewCache[key]) return regionPreviewCache[key];
  regionPreviewCache[key] = { pending: true };
  try {
    const r = await window.go.main.App.RegionPreview(currentProject.id, currentOrder, key);
    regionPreviewCache[key] = r && r.ok
      ? { data_url: (r.result || {}).data_url, label: (r.result || {}).名字, pct: (r.result || {})['区域占全图'], base: (r.result || {}).底图 }
      : { err: (r && (r.error || r.detail)) || '取不到区域预览' };
  } catch (e) {
    regionPreviewCache[key] = { err: String(e) };
  }
  return regionPreviewCache[key];
}

function buildRegionCard(key, labelHint) {
  const card = document.createElement('div');
  card.className = 'region-card';
  const head = document.createElement('div');
  head.className = 'rc-head';
  head.textContent = '它理解的位置（红线框住的那块）';
  const ph = document.createElement('div');
  ph.className = 'rc-ph note';
  ph.textContent = '正在裁那一块…';
  card.appendChild(head);
  card.appendChild(ph);
  const acts = document.createElement('div');
  acts.className = 'rc-acts';
  card.appendChild(acts);

  previewRegion(key).then((pv) => {
    ph.remove();
    if (pv.err) {
      const e = document.createElement('div');
      e.className = 'rc-err';
      e.textContent = '区域预览取不到：' + pv.err;
      card.insertBefore(e, acts);
      return;
    }
    const img = document.createElement('img');
    img.className = 'rc-img';
    img.src = pv.data_url;
    img.alt = `位置预览：${pv.label}`;
    img.title = '点一下放大看';
    img.addEventListener('click', () => openZoomForRegion(pv));
    card.insertBefore(img, acts);
    const meta = document.createElement('div');
    meta.className = 'note rc-meta';
    meta.textContent = `它说的是「${pv.label || labelHint || key}」　占全图 ${pv.pct != null ? pv.pct + '%' : '?'}　底图：${pv.base || '?'}`;
    card.insertBefore(meta, acts);

    const yes = document.createElement('button');
    yes.type = 'button'; yes.className = 'mini primary'; yes.textContent = '对，就是这块';
    yes.addEventListener('click', async () => {
      yes.disabled = true; yes.textContent = '好，我让它继续…';
      await confirmRegion(pv.label || labelHint || key);
    });
    const no = document.createElement('button');
    no.type = 'button'; no.className = 'mini'; no.textContent = '不是这块';
    no.addEventListener('click', () => {
      $('say').value = '不是这块，我想改的是：';
      $('say').focus();
      autogrow();
    });
    acts.appendChild(yes);
    acts.appendChild(no);
  });
  return card;
}

async function confirmRegion(label) {
  if (!currentOrder || busy) return;
  busy = true;
  thinking(true);
  const box = $('chat');
  const msg = `确认：就是「${label}」这块。请按这块继续。`;
  box.insertAdjacentHTML('beforeend',
    `<div class="msg user"><div class="who">你</div><div class="txt">${escapeHtml(msg)}</div></div>`);
  box.scrollTop = box.scrollHeight;
  try {
    const r = await window.go.main.App.IntentRound(currentProject.id, currentOrder, msg);
    if (!r.ok) showErr(r, '确认位置');
  } catch (e) {
    showErr({ error: '调 IntentRound 抛异常', detail: String(e) }, '确认位置');
  } finally {
    busy = false;
    thinking(false);
    await refreshOrder();
    updateComposer();
  }
}

// 区域预览图放大：直接复用放大窗（它本来就是显示一张图 + 缩放平移）
function openZoomForRegion(pv) {
  $('zoomTitle').textContent = '位置预览：' + (pv.label || '');
  $('zoomCap').textContent = `占全图 ${pv.pct != null ? pv.pct + '%' : '?'}　底图：${pv.base || '?'}\n` +
    `（这张只是给你核对位置的，不进账）\n滚轮缩放 ・ 拖动平移 ・ Esc 关闭`;
  $('zoomGrid').classList.add('hidden');
  zState.list = [];
  zState.scale = 0; zState.x = 0; zState.y = 0;
  $('zoom').classList.remove('hidden');
  const img = $('zoomImg');
  img.src = pv.data_url;
  const apply = () => {
    zState.natW = img.naturalWidth || 1;
    zState.natH = img.naturalHeight || 1;
    if (!zState.scale) fitZoom(); else applyZoom();
  };
  if (img.complete && img.naturalWidth) apply(); else img.onload = apply;
}

function renderChat(entries, badLines) {
  const box = $('chat');
  box.innerHTML = '';
  if (badLines) {
    box.insertAdjacentHTML('beforeend',
      `<div class="msg system"><div class="who">系统</div><div class="txt">${badLines} 行流水读不出来（没被丢掉，仍在账里）</div></div>`);
  }
  if (!entries.length) {
    box.innerHTML = '<div class="msg system"><div class="who">系统</div><div class="txt">这一单还没有对话 —— 在下面跟小助手说一句试试。</div></div>';
    return;
  }
  for (const e of entries) {
    const kind = KIND_LABEL[e.kind] ? e.kind : 'system';
    const data = e.data || {};
    let extra = '';
    if (kind === 'assistant' && data.usage) {
      extra = `<div class="ledger">结束原因 ${escapeHtml(data.finish_reason || '?')}` +
              `${data.truncated ? ' ⚠️ 被截断' : ''} ｜ ${data.elapsed_ms || '?'}ms ｜ ${data.usage.totalTokens || '?'} token` +
              `${data.craft ? ' ｜ 工艺 ' + escapeHtml(data.craft) : ''}</div>`;
    }
    box.insertAdjacentHTML('beforeend',
      `<div class="msg ${kind}"><div class="who">${KIND_LABEL[kind]}</div>
       <div class="txt">${escapeHtml(e.text)}</div>${extra}</div>`);
    // ★ 它这一轮说了"我理解的位置是 xxx" ⇒ 在气泡下面挂一张裁剪图 + 确认按钮
    if (kind === 'assistant' && data.region) {
      box.appendChild(buildRegionCard(data.region, e.text));
    }
  }
  box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- 投料
async function feed() {
  clearErr();
  if (!currentProject) { showErr({ error: '先选一个工程', detail: '左边点一下工程，或先新建一个' }, '投料'); return; }
  const path = await window.go.main.App.PickImage();
  if (!path) return;                        // 取消选择是正常结果，不是错误
  const btn = $('btnFeed');
  btn.disabled = true; btn.textContent = '收图中…';
  try {
    const r = await window.go.main.App.NewOrder(currentProject.id, path);
    if (!r.ok) { showErr(r, '投料'); return; }
    await loadProjects();
    await loadOrders();
    const oid = r.result && r.result.order_id;
    if (oid) await openOrder(oid);
  } catch (e) {
    showErr({ error: '调 NewOrder 抛异常', detail: String(e) }, '投料');
  } finally {
    btn.disabled = false; btn.textContent = '＋ 投料（选一张图）';
  }
}

// ---------------------------------------------------------------- 输入框（常驻）
function updateComposer() {
  const ta = $('say'), btn = $('btnSay'), hint = $('sayHint');
  if (!currentProject) {
    ta.disabled = true; btn.disabled = true;
    ta.placeholder = '先在左边选一个工程；没有就新建一个';
    hint.textContent = '① 选工程　→　② 点右上角「＋ 投料」选一张图　→　③ 就能跟小助手说话了';
    return;
  }
  if (!currentOrder) {
    ta.disabled = true; btn.disabled = true;
    ta.placeholder = '这个工程还没有单：先点右上角「＋ 投料（选一张图）」';
    hint.textContent = `当前工程：${currentProject['显示名'] || currentProject.id}　｜　还没有单`;
    return;
  }
  ta.disabled = false; btn.disabled = busy;
  ta.placeholder = '说一句，例如：把这个做成玻璃画　／　不是，我想做个模型';
  hint.textContent = `正在说给：${currentProject['显示名'] || currentProject.id}　／　${currentOrder}`;
}

function autogrow() {
  const ta = $('say');
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
}

function thinking(on) {
  $('thinking').classList.toggle('hidden', !on);
  const btn = $('btnSay');
  btn.disabled = on || !currentOrder;
  btn.textContent = on ? '它在想…' : '发送';
}

async function say() {
  clearErr();
  if (busy) return;
  if (!currentOrder) {
    showErr({ error: '还没有单', detail: '先点右上角「＋ 投料（选一张图）」，建一单再说话' }, '发送');
    return;
  }
  const input = $('say');
  const text = (input.value || '').trim();
  if (!text) { showErr({ error: '还没说话', detail: '写一句再发；比如「把这个做成玻璃画」' }, '发送'); input.focus(); return; }

  busy = true;
  input.value = '';
  input.style.height = '';
  const box = $('chat');
  box.insertAdjacentHTML('beforeend',
    `<div class="msg user"><div class="who">你</div><div class="txt">${escapeHtml(text)}</div></div>`);
  box.scrollTop = box.scrollHeight;
  thinking(true);

  try {
    const r = await window.go.main.App.IntentRound(currentProject.id, currentOrder, text);
    if (!r.ok) { showErr(r, '问小助手'); return; }
    const res = r.result || {};
    if (res['合法'] === false) {
      showErr({ error: '小助手的回答没通过校验（整轮作废，已记账）', detail: res['不合法原因'] }, '校验');
    }
  } catch (e) {
    showErr({ error: '调 IntentRound 抛异常', detail: String(e) }, '问小助手');
  } finally {
    busy = false;
    thinking(false);
    await refreshOrder();     // ★ 用账重画一遍
    updateComposer();
    input.focus();
  }
}

// ---------------------------------------------------------------- 启动
window.addEventListener('DOMContentLoaded', async () => {
  $('btnNew').addEventListener('click', createProject);
  $('newName').addEventListener('keydown', (e) => { if (e.key === 'Enter') createProject(); });
  $('btnFeed').addEventListener('click', feed);
  $('btnSay').addEventListener('click', say);

  // ---- 预览：放大 / 格号 / 单张 ----
  $('btnGrid').addEventListener('click', () => {
    gridOn = !gridOn;
    $('btnGrid').classList.toggle('on', gridOn);
    $('zoomGrid').classList.toggle('hidden', !gridOn);
    renderPanes();
  });
  $('btnView').addEventListener('click', () => openZoom((cmp.length ? cmp[cmp.length - 1] : versions[versions.length - 1].ver), undefined));
  $('btnOne').addEventListener('click', () => {
    cmp = [versions[versions.length - 1].ver];
    renderBar();
    renderPanes();
  });

  // ---- 放大窗口 ----
  $('btnZoomClose').addEventListener('click', closeZoom);
  $('btnZoomIn').addEventListener('click', () => zoomStep(1.25));
  $('btnZoomOut').addEventListener('click', () => zoomStep(0.8));
  $('btnZoomFit').addEventListener('click', fitZoom);
  $('btnZoomOne').addEventListener('click', () => { zState.scale = 1; zState.x = 0; zState.y = 0; applyZoom(); });
  $('btnZoomGrid').addEventListener('click', () => {
    gridOn = !gridOn;
    $('btnGrid').classList.toggle('on', gridOn);
    $('zoomGrid').classList.toggle('hidden', !gridOn);
    $('zoomGrid').innerHTML = gridOn ? buildGrid().innerHTML : '';
    renderPanes();
  });
  $('btnZoomPrev').addEventListener('click', () => zoomStepVer(-1));
  $('btnZoomNext').addEventListener('click', () => zoomStepVer(1));
  $('zoomStage').addEventListener('wheel', (e) => {
    e.preventDefault();
    zoomStep(e.deltaY < 0 ? 1.15 : 0.87, e.clientX, e.clientY);
  }, { passive: false });
  (function dragPan() {
    const stage = $('zoomStage');
    let on = false, sx = 0, sy = 0, ox = 0, oy = 0;
    stage.addEventListener('mousedown', (e) => {
      if ($('zoom').classList.contains('hidden')) return;
      on = true; sx = e.clientX; sy = e.clientY; ox = zState.x; oy = zState.y;
      stage.classList.add('dragging');
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!on) return;
      zState.x = ox + (e.clientX - sx);
      zState.y = oy + (e.clientY - sy);
      applyZoom();
    });
    window.addEventListener('mouseup', () => { on = false; stage.classList.remove('dragging'); });
  })();
  window.addEventListener('keydown', (e) => {
    if ($('zoom').classList.contains('hidden')) return;
    if (e.key === 'Escape') closeZoom();
    else if (e.key === ' ') { e.preventDefault(); $('btnZoomGrid').click(); }
    else if (e.key === 'ArrowLeft') zoomStepVer(-1);
    else if (e.key === 'ArrowRight') zoomStepVer(1);
    else if (e.key === '+' || e.key === '=') zoomStep(1.25);
    else if (e.key === '-') zoomStep(0.8);
  });
  $('say').addEventListener('input', autogrow);
  $('say').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); say(); }   // Enter 发送
  });                                                                       // Shift+Enter 换行

  try {
    await loadProjects();
    await loadKernelStatus();
    // ★ 一打开就回到"最近动过的那一单"：走后端（可无头验证），
    //   不在前端猜——内核的工程列表恒把「默认工程」排第一，猜必错。
    const lr = await window.go.main.App.SessionLatest();
    const latest = lr.ok && lr.result && lr.result.latest;
    if (latest && latest.project) {
      const p = projects.find((x) => x.id === latest.project);
      if (p) {
        await selectProject(p, latest.order_id);
      }
    } else if (projects.length) {
      await selectProject(projects[0]);
    }
  } catch (e) {
    showErr({ error: '初始化失败（Go 绑定可能没就绪）', detail: String(e) }, '启动');
  } finally {
    updateComposer();
  }
});
