// app.js —— 画台（第 4b 步：能投料、能跟小助手说话）
//
// 两条规矩：
// 1. **界面不自己编状态**：所有内容都来自内核（Go 壳 → Python → 账）。
// 2. **点下去立刻有反馈**：用户的话先上屏、再显示"它在想…"，最后用**账**重画一遍
//    （账是唯一真相，界面只是它的一个显示）。

const $ = (id) => document.getElementById(id);

let projects = [];
let currentProject = null;   // 工程
let currentOrder = null;     // 单号
let busy = false;

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
    if (st.running) {
      badge.textContent = `内核：运行中（PID ${st.pid}）`;
      badge.className = 'badge ok';
    } else if (st.root) {
      badge.textContent = '内核：就绪（待首次调用）';
      badge.className = 'badge';
    } else {
      badge.textContent = '内核：异常';
      badge.className = 'badge bad';
      showErr({ error: '找不到项目根', detail: st.lastErr }, '内核定位');
    }
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
  if (!projects.length) {
    ul.innerHTML = '<li class="empty">还没有工程</li>';
    return;
  }
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
    if (found) selectProject(found);
  } catch (e) {
    showErr({ error: '调 NewProject 抛异常', detail: String(e) }, '新建工程');
  } finally {
    btn.disabled = false; btn.textContent = '新建';
  }
}

// ---------------------------------------------------------------- 工程 → 单列表
async function selectProject(p) {
  currentProject = p;
  currentOrder = null;
  renderProjects();
  $('crumb').textContent = p['显示名'] || p.id;
  $('orderView').classList.add('hidden');
  $('projView').classList.remove('hidden');
  updateComposer();
  await loadOrders();
}

async function loadOrders() {
  if (!currentProject) return;
  const r = await window.go.main.App.Orders(currentProject.id);
  if (!r.ok) { showErr(r, '读单列表'); return; }
  const orders = (r.result && r.result.orders) || [];
  $('meta').textContent = `目录名 ${currentProject.id} ｜ ${orders.length} 单`;
  const ul = $('orders');
  ul.innerHTML = '';
  if (!orders.length) {
    ul.innerHTML = '<li class="empty">这个工程还没有单 —— 点上面的「投料」选一张图</li>';
    return;
  }
  for (const o of orders) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="nm">${escapeHtml(o.src_name || o.order_id)}</span>
                    <span class="ct">${o.n_ver || 0} 版</span>`;
    li.addEventListener('click', () => openOrder(o));
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------- 投料
async function feed() {
  clearErr();
  if (!currentProject) { showErr({ error: '先选一个工程', detail: '左边点一下工程' }, '投料'); return; }
  const path = await window.go.main.App.PickImage();
  if (!path) return;                       // 取消选择是正常结果，不是错误
  const btn = $('btnFeed');
  btn.disabled = true; btn.textContent = '收图中…';
  try {
    const r = await window.go.main.App.NewOrder(currentProject.id, path);
    if (!r.ok) { showErr(r, '投料'); return; }
    await loadOrders();
    await loadProjects();
    const oid = r.result && r.result.order_id;
    if (oid) await openOrder({ order_id: oid, src_name: r.result.src });
  } catch (e) {
    showErr({ error: '调 NewOrder 抛异常', detail: String(e) }, '投料');
  } finally {
    btn.disabled = false; btn.textContent = '＋ 投料（选一张图）';
  }
}

// ---------------------------------------------------------------- 单视图 + 对话
async function openOrder(o) {
  currentOrder = o.order_id;
  $('projView').classList.add('hidden');
  $('orderView').classList.remove('hidden');
  updateComposer();
  await refreshOrder();
  $('say').focus();
}

async function refreshOrder() {
  const r = await window.go.main.App.OrderDetail(currentProject.id, currentOrder);
  if (!r.ok) { showErr(r, '读这一单'); return; }
  const d = r.result;
  $('ocrumb').textContent = `单 ${d['订单'] && d['订单'].order_id} ｜ 料 ${(d['订单'] && d['订单'].src_name) || ''} ｜ 产物 ${(d['产物'] || []).length} 个`;
  renderChat(d['流水'] || [], d['流水坏行'] || 0);
}

const KIND_LABEL = {
  material: '料', user: '你', assistant: '小助手', action: '动作', system: '系统',
};

function renderChat(entries, badLines) {
  const box = $('chat');
  box.innerHTML = '';
  if (badLines) {
    box.insertAdjacentHTML('beforeend',
      `<div class="msg system"><div class="who">系统</div><div class="txt">${badLines} 行流水读不出来（没被丢掉，已在账里）</div></div>`);
  }
  if (!entries.length) {
    box.innerHTML = '<div class="msg system"><div class="who">系统</div><div class="txt">这一单还没有对话</div></div>';
    return;
  }
  for (const e of entries) {
    const kind = KIND_LABEL[e.kind] ? e.kind : 'system';
    const div = document.createElement('div');
    div.className = `msg ${kind}`;
    const data = e.data || {};
    let extra = '';
    if (kind === 'assistant' && data.usage) {
      extra = `<div class="ledger">结束原因 ${escapeHtml(data.finish_reason || '?')}` +
              `${data.truncated ? ' ⚠️ 被截断' : ''} ｜ ${data.elapsed_ms || '?'}ms ｜ ${data.usage.totalTokens || '?'} token` +
              `${data.craft ? ' ｜ 工艺 ' + escapeHtml(data.craft) : ''}</div>`;
    }
    div.innerHTML = `<div class="who">${KIND_LABEL[kind]}</div>
                     <div class="txt">${escapeHtml(e.text)}</div>${extra}`;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

function thinking(on) {
  $('thinking').classList.toggle('hidden', !on);
  const btn = $('btnSay');
  btn.disabled = on || !currentOrder;
  btn.textContent = on ? '它在想…' : '发送';
}

// ---------------------------------------------------------------- 输入框的启用与说明
// ★ 输入框常驻底部：**没打开单时禁用并写明原因**，而不是干脆不显示（那样用户会以为没有输入框）。
function updateComposer() {
  const ta = $('say');
  const btn = $('btnSay');
  const hint = $('sayHint');

  if (!currentProject) {
    ta.disabled = true; btn.disabled = true;
    ta.placeholder = '先在左边选一个工程；没有就新建一个';
    hint.textContent = '① 选工程　→　② 点「＋ 投料（选一张图）」建单　→　③ 就能跟小助手说话了';
    return;
  }
  if (!currentOrder) {
    ta.disabled = true; btn.disabled = true;
    ta.placeholder = '先点上面「＋ 投料（选一张图）」，建一张单，再说话';
    hint.textContent = `当前工程：${currentProject['显示名'] || currentProject.id}　｜　还没有打开的单`;
    return;
  }
  ta.disabled = false; btn.disabled = busy;
  ta.placeholder = '说一句，例如：把这个做成玻璃画　／　不是，我想做个模型';
  hint.textContent = `正在说给：${currentProject['显示名'] || currentProject.id}　／　单 ${currentOrder}`;
}

function autogrow() {
  const ta = $('say');
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
}

async function say() {
  clearErr();
  if (busy) return;
  if (!currentOrder) {
    showErr({ error: '还没有打开的单', detail: '先投料（选一张图）建一张单，再跟小助手说话' }, '发送');
    return;
  }
  const input = $('say');
  const text = (input.value || '').trim();
  if (!text) { showErr({ error: '还没说话', detail: '写一句再发；比如「把这个做成玻璃画」' }, '发送'); input.focus(); return; }

  busy = true;
  input.value = '';
  input.style.height = '';
  // ★ 点下去立刻有反馈：先把我的话上屏，再显示"它在想…"
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
    await refreshOrder();     // ★ 用**账**重画一遍（账是唯一真相）
    updateComposer();
    input.focus();
  }
}

// ---------------------------------------------------------------- 启动
window.addEventListener('DOMContentLoaded', async () => {
  $('btnNew').addEventListener('click', createProject);
  $('newName').addEventListener('keydown', (e) => { if (e.key === 'Enter') createProject(); });
  $('btnFeed').addEventListener('click', feed);
  $('btnBack').addEventListener('click', () => {
    currentOrder = null;
    $('orderView').classList.add('hidden');
    $('projView').classList.remove('hidden');
    updateComposer();
    loadOrders();
  });
  $('btnSay').addEventListener('click', say);
  $('say').addEventListener('input', autogrow);
  $('say').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); say(); }   // Enter 发送
  });                                                                       // Shift+Enter 换行

  try {
    await loadProjects();
    await loadKernelStatus();
  } catch (e) {
    showErr({ error: '初始化失败（Go 绑定可能没就绪）', detail: String(e) }, '启动');
  } finally {
    updateComposer();
  }
});
