'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
let state = null;
let selected = new Set();
let initialized = false;
let pending = false;
let online = true;
let dirty = false;
let stoppingApp = false;
let toastTimer;
let saveTimer;
let renderedRows = '';
let renderedLogs = '';
let renderedAccount = '';
let lastScanSeen = null;
let lastAccountSeen = null;
let selectionProfile = null;
let excluded = new Set();
let aiTesting = false;
const icon = name => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  svg.setAttribute('aria-hidden', 'true');
  return svg;
};
const number = n => String(n).padStart(2, '0');
const eligibleRow = row => ['verified', 'history_confirmed'].includes(row.streak_status);
const recoveryNotice = row => row.history_evidence?.recovery;
const selectableRow = row => eligibleRow(row) || ($('auto-restore').checked && recoveryNotice(row)?.status === 'available' && recoveryNotice(row).deadline_at * 1000 > Date.now());
function replyToday(row) {
  if (!row.reply?.day || !row.reply?.timezone) return 'unknown';
  try {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone: row.reply.timezone, year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date()).map(part => [part.type, part.value]));
    return row.reply.day === `${parts.year}-${parts.month}-${parts.day}` ? row.reply.status : 'unknown';
  } catch { return 'unknown'; }
}
function loadExclusions() {
  try {
    const values = JSON.parse(localStorage.getItem(selectionProfile) || '[]');
    excluded = new Set(Array.isArray(values) ? values.filter(value => typeof value === 'string') : []);
  } catch { excluded = new Set(); }
}
function saveChoice(key, checked) {
  if (checked) { excluded.delete(key); selected.add(key); }
  else { excluded.add(key); selected.delete(key); }
  if (selectionProfile) {
    try { localStorage.setItem(selectionProfile, JSON.stringify([...excluded])); } catch {}
  }
}
function syncSelection() {
  const username = state.account?.authenticated ? state.account.username : null;
  const profile = username ? `streak.excluded.v1:${state.status.channel}:${encodeURIComponent(username.toLowerCase())}` : null;
  if (profile !== selectionProfile) {
    selectionProfile = profile;
    selected.clear();
    if (profile) loadExclusions(); else excluded.clear();
  }
  const available = new Set(state.rows.filter(selectableRow).map(row => row.key));
  selected = new Set([...selected].filter(key => available.has(key)));
  if (!profile || $('browser-select').value !== state.status.channel) { selected.clear(); return; }
  if (state.status.busy || state.status.rows_cached || state.status.account_checking) return;
  // Keep completed chats in the daily schedule; the worker skips today's replies.
  // Explicit exclusions survive polling, refreshes and reopening this account.
  selected = new Set(state.rows.filter(row => selectableRow(row) && !excluded.has(row.key)).map(row => row.key));
}
function notify(message, error = false) {
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').hidden = true, error ? 6500 : 3500);
}
function settings() {
  return {message: $('message').value, hours: Number($('hours').value), channel: $('browser-select').value, auto_restore: $('auto-restore').checked,
    ai_enabled: $('ai-enabled').checked, ai_style: $('ai-style').value, daily_mode: $('daily-mode').value, video_query: $('video-query').value};
}
async function api(path, data) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-App-Token': token}, body: JSON.stringify(data)});
  if (response.status === 401) { location.assign('/login'); throw new Error('Phiên đăng nhập đã hết hạn.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Không thực hiện được thao tác.');
  return result;
}
function updatePreview() {
  const count = Array.from($('message').value).length;
  $('char-count').textContent = `${count} / 500`;
  $('preview-bubble').textContent = $('message').value || 'Lời nhắn của bạn sẽ xuất hiện ở đây…';
  $('interval-preview').textContent = `${$('hours').value || '—'} giờ`;
  if (state) updateControls();
}
function scheduleSave() {
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    if (!state || pending || state.status.busy || state.status.automatic || !online) return;
    const data = settings();
    if (!Number.isFinite(data.hours) || data.hours < 1 || data.hours > 168) return;
    try {
      await api('/api/settings', data);
      if (JSON.stringify(data) === JSON.stringify(settings())) dirty = false;
    } catch (error) { notify(error.message, true); }
  }, 700);
}
function filteredRows() {
  const query = $('search').value.trim().toLocaleLowerCase('vi');
  const filter = $('streak-filter').value;
  return (state?.rows || []).filter(row => row.name.toLocaleLowerCase('vi').includes(query) &&
    (filter === 'all' || (filter === 'recovery' ? Boolean(recoveryNotice(row)) : filter === 'verified' ? eligibleRow(row) : filter === 'needed' ? eligibleRow(row) && replyToday(row) === 'needed' : filter === 'replied' ? eligibleRow(row) && replyToday(row) === 'replied' : !eligibleRow(row))));
}
function renderFriends() {
  if (!state) return;
  const visible = filteredRows();
  const signature = JSON.stringify([state.rows, state.rows.map(replyToday), [...selected], $('auto-restore').checked, $('search').value, $('streak-filter').value, state.status.busy, state.status.automatic, state.status.rows_cached, state.status.account_checking]);
  if (signature === renderedRows) return;
  renderedRows = signature;
  const list = $('friend-list');
  const fragment = document.createDocumentFragment();
  for (const row of visible) {
    const label = document.createElement('label');
    const verified = eligibleRow(row);
    label.className = 'friend-row' + (selected.has(row.key) ? ' chosen' : '') + (verified ? '' : ' unverified');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = selected.has(row.key);
    checkbox.disabled = state.status.busy || state.status.automatic || state.status.rows_cached || state.status.account_checking || !selectableRow(row);
    checkbox.setAttribute('aria-label', 'Chọn ' + row.name);
    checkbox.addEventListener('change', () => {
      saveChoice(row.key, checkbox.checked);
      renderFriends(); updateCounts(); updateControls();
    });
    const avatar = document.createElement('span');
    avatar.className = 'friend-avatar';
    avatar.textContent = row.name.trim().split(/\s+/).slice(-2).map(s => Array.from(s)[0] || '').join('').toUpperCase();
    const name = document.createElement('span');
    name.className = 'friend-name'; name.textContent = row.name;
    const sub = document.createElement('span');
    const reply = replyToday(row);
    sub.className = 'friend-sub' + (reply === 'replied' ? ' replied' : '');
    sub.textContent = (row.is_group ? 'Nhóm · ' : '') + (reply === 'replied' ? 'Bạn đã rep hôm nay · Tool tự bỏ qua' : reply === 'needed' ? 'Bạn chưa rep hôm nay' : row.streak_status === 'history_confirmed' ? 'Thông báo chuỗi TikTok · Chưa kiểm tra rep hôm nay' : verified ? 'Đã xác minh huy hiệu chuỗi' : 'Chưa có trạng thái chuỗi hiện tại'); name.append(sub);
    if (recoveryNotice(row)) sub.textContent = row.recovery?.reason || (recoveryNotice(row).status === 'expired' ? 'Đã quá hạn khôi phục của TikTok' : 'Đã mất chuỗi · Chờ khôi phục trước khi gửi tiếp');
    const badge = document.createElement('span');
    badge.className = 'friend-badge' + (verified ? '' : ' unknown'); badge.title = row.streak_status === 'history_confirmed' ? `Đối chiếu thông báo chuỗi ngày ${row.history_evidence.marker_day} với lịch sử trao đổi. Số ngày hiển thị là mức tối thiểu quan sát được (${row.history_evidence.timezone}).` : row.badge || 'Không đủ dữ liệu để xác minh chuỗi';
    badge.append(icon(verified ? 'fire' : 'clock'));
    const days = (row.badge || '').match(/\b(\d{1,5})\b/);
    badge.append(document.createTextNode(verified ? (days ? `${row.streak_status === 'history_confirmed' ? '≥' : ''}${days[1]} ngày` : 'Đã xác minh') : 'Chưa xác minh'));
    if (recoveryNotice(row)) { badge.replaceChildren(icon('refresh'), document.createTextNode(recoveryNotice(row).status === 'expired' ? 'Hết hạn khôi phục' : 'Cần khôi phục')); badge.title = 'TikTok báo mất chuỗi ngày ' + recoveryNotice(row).ended_day; }
    label.append(checkbox, avatar, name, badge); fragment.append(label);
  }
  list.replaceChildren(fragment);
  $('empty-state').hidden = state.rows.length > 0;
  $('no-results').hidden = !state.rows.length || visible.length > 0;
  $('no-results').textContent = $('search').value.trim() ? 'Không có tên phù hợp với tìm kiếm.' : $('streak-filter').value === 'verified' ? 'Chưa tìm được cuộc trò chuyện có đủ bằng chứng chuỗi.' : 'Không có cuộc trò chuyện trong nhóm này.';
  const eligible = visible.filter(selectableRow);
  const chosenVisible = eligible.filter(row => selected.has(row.key)).length;
  $('select-all').checked = eligible.length > 0 && chosenVisible === eligible.length;
  $('select-all').indeterminate = chosenVisible > 0 && chosenVisible < eligible.length;
}
function updateCounts() {
  if (!state) return;
  const verified = state.rows.filter(row => eligibleRow(row)).length;
  const unknown = state.rows.length - verified;
  const history = state.rows.filter(row => row.streak_status === 'history_confirmed').length;
  const replied = state.rows.filter(row => eligibleRow(row) && replyToday(row) === 'replied').length;
  const groups = state.rows.filter(row => eligibleRow(row) && row.is_group).length;
  $('streak-count').textContent = state.status.scanned_at && (verified > 0 || unknown === 0) ? number(verified) : '—';
  $('selected-count').textContent = number(selected.size);
  $('sent-count').textContent = number(state.status.sent);
  $('friends-count').textContent = state.rows.length;
  $('nav-count').textContent = state.rows.length;
  $('scan-hint').textContent = state.status.scanned_at ? (history ? `${history} qua thông báo + lịch sử TikTok` : unknown ? `${unknown} cuộc trò chuyện chưa có trạng thái` : `Đã đọc ${state.status.total ?? state.rows.length} cuộc trò chuyện`) : 'Quét danh sách để cập nhật';
  $('scan-notice').hidden = !unknown && !history;
  $('scan-notice').textContent = history ? `Tự tìm được ${history} cuộc trò chuyện có thông báo chuỗi TikTok, gồm cả chuỗi đã khôi phục; đã đối chiếu các ngày sau thông báo. Số ngày ≥ là mức tối thiểu từ bằng chứng đã đọc, chưa phải bộ đếm trực tiếp. ${unknown} cuộc trò chuyện khác chưa đủ bằng chứng.` : unknown ? `Đã tự đọc ${state.status.total ?? state.rows.length} cuộc trò chuyện. ${unknown} người chưa có đủ bằng chứng chuỗi. Các dòng “Chưa xác minh” chưa đủ điều kiện gửi tự động.` : '';
  if (groups || replied) {
    $('scan-notice').hidden = false;
    $('scan-notice').textContent += ` Có ${groups} nhóm có chuỗi. ${replied} chat bạn đã rep hôm nay sẽ được tự bỏ qua; tool kiểm tra lại ngay trước khi gửi.`;
  }
  const lost = state.rows.filter(row => recoveryNotice(row));
  if (lost.length) {
    $('scan-notice').hidden = false;
    $('scan-notice').textContent += ` ${lost.length} chuỗi đã mất (${lost.slice(0, 3).map(row => row.name).join(', ')}). ` + ($('auto-restore').checked ? 'Tool tự kiểm tra khôi phục cho các chat đã chọn khi TikTok còn cho phép.' : 'Bật Tự khôi phục chuỗi nếu bạn muốn tool xử lý các chat này.');
  }
  if (state.status.rows_cached) {
    $('scan-notice').hidden = false;
    $('scan-notice').textContent = state.status.busy && state.status.operation === 'scan' ? 'Đang hiển thị danh sách lần quét trước của tài khoản này. Tool đang kiểm tra lại; chờ cập nhật xong để chọn và gửi.' : 'Danh sách lần quét trước của tài khoản này đã được khôi phục. Cần quét cập nhật trước khi chọn và gửi.';
  } else if (state.status.busy && state.status.operation === 'scan' && state.rows.length) {
    $('scan-notice').hidden = false;
    $('scan-notice').textContent = 'Đang cập nhật cuộc trò chuyện và chuỗi. Danh sách lần quét trước vẫn được giữ trên màn hình.';
  }
}
function setAvatar(element, account) {
  element.replaceChildren();
  const initial = Array.from(account?.display_name || account?.username || 'S')[0];
  element.textContent = initial;
  try {
    const url = new URL(account?.avatar_url || '');
    const suffixes = ['.tiktokcdn.com', '.tiktokcdn-us.com', '.tiktokcdn-eu.com', '.byteoversea.com', '.ibytedtos.com'];
    if (url.protocol !== 'https:' || !suffixes.some(suffix => url.hostname.endsWith(suffix))) return;
    const image = document.createElement('img');
    image.alt = account.display_name || account.username;
    image.referrerPolicy = 'no-referrer';
    image.src = url.href;
    image.addEventListener('error', () => { element.textContent = initial; }, {once:true});
    element.replaceChildren(image);
  } catch {}
}
function renderAccount() {
  const remote = state.runtime?.mode === 'vps';
  $('web-logout').hidden = !remote || location.protocol !== 'https:';
  $('browser-screen').hidden = !remote;
  $('browser-screen').href = location.protocol === 'https:' ? '/browser/' : 'http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale';
  $('shutdown-label').textContent = remote ? 'Dừng giữ chuỗi' : 'Tắt ứng dụng';
  $('runtime-label').textContent = remote ? 'Đang chạy trên VPS' : 'Chạy trên máy của bạn';
  $('runtime-location').textContent = remote ? 'VPS Ubuntu' : 'Local workspace';
  $('daily-schedule').querySelector('p').textContent = remote ? 'Theo giờ Việt Nam (UTC+7) trên VPS' : 'Theo giờ trên máy tính của bạn';
  const connected = Boolean(state.account?.authenticated && state.status.browser_connected);
  const signature = JSON.stringify([state.account, state.status.browser_connected, state.status.operation, state.status.scanned_at, state.status.total]);
  if (signature === renderedAccount) return;
  renderedAccount = signature;
  const account = connected ? state.account : null;
  $('workspace-name').textContent = account ? account.display_name : 'Tài khoản TikTok';
  $('workspace-handle').textContent = account ? '@' + account.username : state.status.browser_connected ? 'Đang chờ đăng nhập' : 'Chưa kết nối';
  $('account-top-name').textContent = account ? account.display_name : 'Tài khoản TikTok';
  $('account-top-handle').textContent = account ? '@' + account.username : state.status.operation === 'restore' ? 'Đang khôi phục phiên…' : 'Chưa đăng nhập';
  $('top-avatar').parentElement.classList.toggle('connected', connected);
  setAvatar($('workspace-avatar'), account);
  setAvatar($('top-avatar'), account);
  $('hero-login-label').textContent = connected ? 'Mở TikTok' : 'Kết nối TikTok';
  $('qr-login').hidden = connected;
  $('page-subtitle').textContent = account ? `Đã đăng nhập @${account.username}. Sẵn sàng giữ lửa cùng bạn bè.` : 'Chăm chút những cuộc trò chuyện, giữ lửa cùng bạn bè.';
  $('empty-action-label').textContent = connected ? 'Quét danh sách' : 'Bắt đầu kết nối';
  $('empty-title').textContent = !connected ? 'Những kết nối đang chờ bạn' : state.status.scanned_at ? 'Chưa thấy huy hiệu chuỗi' : 'Tài khoản đã sẵn sàng';
  $('empty-description').textContent = !connected ? 'Đăng nhập TikTok rồi quét danh sách. Những người có huy hiệu chuỗi sẽ xuất hiện ở đây.' : state.status.scanned_at ? `Đã đọc ${state.status.total ?? 0} cuộc trò chuyện. Nếu TikTok web không hiển thị huy hiệu chuỗi, tool chưa thể xác định người có lửa.` : 'Bấm Quét danh sách để tìm những người đang có huy hiệu chuỗi trên TikTok.';
}
function updateControls() {
  if (!state) return;
  const s = state.status;
  const busy = pending || s.busy;
  const locked = busy || s.automatic || !online;
  for (const id of ['message', 'hours', 'hours-minus', 'hours-plus', 'browser-select', 'search', 'auto-restore','ai-enabled','ai-style','daily-mode','video-query']) $(id).disabled = locked;
  $('ai-test').disabled = aiTesting || !online || !state.ai?.configured;
  $('video-preview').disabled = busy || !online || !state.ai?.configured || !state.account?.authenticated;
  $('ai-model').textContent = state.ai?.configured ? state.ai.model : 'Chưa cấu hình AI';
  for (const id of ['hero-login', 'qr-login', 'empty-login', 'account-refresh']) $(id).disabled = locked;
  $('scan-button').disabled = locked || !s.browser_connected || !state.account?.authenticated;
  const unconfirmed = s.rows_cached || s.account_checking;
  $('select-all').disabled = locked || unconfirmed || !filteredRows().some(selectableRow);
  $('streak-filter').disabled = locked;
  const valid = $('message').value.trim() && Number.isFinite(Number($('hours').value)) && Number($('hours').value) >= 1 && Number($('hours').value) <= 168;
  $('send-button').disabled = locked || unconfirmed || !selected.size || !valid;
  $('auto-button').disabled = locked || unconfirmed || !selected.size || !valid;
  $('stop-button').hidden = !(busy || s.automatic);
  $('stop-button').disabled = !online || pending;
  $('send-actions')?.classList.toggle('running', s.automatic);
  const repliedSelected = state.rows.filter(row => selected.has(row.key) && replyToday(row) === 'replied').length;
  const note = !online ? 'Mở lại start.bat để kết nối với ứng dụng.' : s.automatic ? 'Đang giữ chuỗi theo ngày. Qua 00:00 tự kiểm tra chat chưa rep; bấm Dừng để thay đổi.' : busy ? ({login: 'Đang mở cửa sổ TikTok…', restore: 'Đang khôi phục phiên đăng nhập…', account: 'Đang cập nhật tài khoản TikTok…', scan: s.history_total ? `Đang kiểm tra lịch sử ${s.history_checked}/${s.history_total} · Đã tìm được ${s.history_matches} chuỗi…` : 'Đang đọc danh sách cuộc trò chuyện…', send: 'Đang kiểm tra người nhận và gửi tin…', auto: 'Đang bắt đầu lượt giữ chuỗi…'}[s.operation] || 'Đang thực hiện, bạn chờ một chút…') : selected.size ? `Đã chọn ${selected.size} chat giữ chuỗi.` + (repliedSelected ? ` ${repliedSelected} chat đã rep hôm nay sẽ được bỏ qua.` : '') : 'Tool tự chọn các chat đủ bằng chứng chuỗi. Bạn có thể chọn lại nếu đã bỏ chọn.';
  $('send-note').textContent = note;
  if (!busy && unconfirmed) $('send-note').textContent = s.account_checking ? 'TikTok đang tải lại. Đang xác nhận phiên đăng nhập; danh sách vẫn được giữ.' : 'Danh sách đã lưu đang chờ cập nhật. Bấm Quét danh sách để kiểm tra lại trước khi gửi.';
  $('scan-button').querySelector('svg').classList.toggle('spinning', s.operation === 'scan');
  $('scan-button').querySelector('span').textContent = s.operation === 'scan' ? (s.history_total ? `${s.history_checked}/${s.history_total}` : 'Đang quét…') : 'Quét danh sách';
  if (s.busy && s.operation === 'scan') {
    $('empty-title').textContent = 'Đang tải cuộc trò chuyện và tìm chuỗi…';
    $('empty-description').textContent = s.history_total ? `Đã đối chiếu ${s.history_checked}/${s.history_total} cuộc trò chuyện gần đây, tìm được ${s.history_matches} chuỗi. Danh sách sẽ hiện khi quét xong.` : 'Đang đọc danh sách chat TikTok. Danh sách sẽ tự hiện khi quét xong.';
    $('scan-hint').textContent = s.history_total ? `Đang kiểm tra ${s.history_checked}/${s.history_total} cuộc trò chuyện gần đây` : 'Đang tải danh sách chat…';
  }
  const browserName = s.channel === 'msedge' ? 'Edge' : 'Chrome';
  $('browser-status').textContent = !online ? 'Mất kết nối với tool' : state.account?.authenticated && s.browser_connected ? `Đã đăng nhập · @${state.account.username}` : s.browser_connected ? `${browserName} đang chờ bạn đăng nhập` : 'Chưa mở trình duyệt TikTok';
  if (online && s.account_checking) $('browser-status').textContent = 'Đang xác nhận phiên TikTok…';
  $('browser-dot').className = 'dot' + (online && s.browser_connected && state.account?.authenticated ? ' green' : '');
}
function renderActivity() {
  const signature = JSON.stringify(state.logs.map(log => log.id));
  if (signature === renderedLogs) return;
  renderedLogs = signature;
  const fragment = document.createDocumentFragment();
  for (const entry of [...state.logs].reverse()) {
    const row = document.createElement('div'); row.className = 'activity-item ' + entry.level;
    const mark = document.createElement('span'); mark.className = 'activity-icon'; mark.append(icon(entry.level === 'success' ? 'check' : entry.level === 'error' ? 'help' : 'clock'));
    const text = document.createElement('div'); text.className = 'activity-text'; text.textContent = entry.text;
    const time = document.createElement('time'); const date = new Date(entry.at * 1000);
    time.dateTime = date.toISOString(); time.textContent = date.toLocaleTimeString('vi-VN', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    row.append(mark, text, time); fragment.append(row);
  }
  $('activity-list').replaceChildren(fragment);
}
async function poll() {
  if (stoppingApp) return;
  try {
    const response = await fetch('/api/state?v=2', {cache: 'no-store'});
    if (response.status === 401) { stoppingApp = true; location.assign('/login'); return; }
    if (!response.ok) throw new Error('Không nhận được trạng thái.');
    state = await response.json();
    const accountName = state.account?.username || null;
    if (accountName !== lastAccountSeen) selected.clear();
    lastAccountSeen = accountName;
    online = true;
    $('offline-banner').hidden = true;
    if (!initialized) {
      $('message').value = state.settings.message;
      $('hours').value = state.settings.hours;
      $('browser-select').value = state.settings.channel;
      $('auto-restore').checked = state.settings.auto_restore === true;
      $('ai-enabled').checked = state.settings.ai_enabled === true;
      $('ai-style').value = state.settings.ai_style || 'Viết tự nhiên, thân thiện bằng tiếng Việt, ngắn gọn.';
      $('daily-mode').value = state.settings.daily_mode || 'text';
      $('video-query').value = state.settings.video_query || 'chuỗi';
      initialized = true;
      updatePreview();
    } else if (!dirty && !pending && document.activeElement !== $('message') && document.activeElement !== $('hours') && document.activeElement !== $('browser-select')) {
      $('message').value = state.settings.message;
      $('hours').value = state.settings.hours;
      $('browser-select').value = state.settings.channel;
      $('auto-restore').checked = state.settings.auto_restore === true;
      $('ai-enabled').checked = state.settings.ai_enabled === true;
      $('ai-style').value = state.settings.ai_style || 'Viết tự nhiên, thân thiện bằng tiếng Việt, ngắn gọn.';
      $('daily-mode').value = state.settings.daily_mode || 'text';
      $('video-query').value = state.settings.video_query || 'chuỗi';
      updatePreview();
    }
    syncSelection();
    if (state.status.scanned_at && state.status.scanned_at !== lastScanSeen) {
      lastScanSeen = state.status.scanned_at;
      if (state.rows.some(eligibleRow)) $('streak-filter').value = 'verified';
    }
    renderAccount(); updateCounts(); renderFriends(); renderActivity(); updateControls(); renderVideo();
  } catch {
    online = false;
    $('offline-banner').hidden = false;
    if (state) updateControls();
  } finally {
    if (!stoppingApp) setTimeout(poll, 900);
  }
}
async function action(command, method = 'standard') {
  if (pending) return;
  if (!state) { notify('Đang kết nối với ứng dụng, bạn chờ một chút.'); return; }
  pending = true;
  clearTimeout(saveTimer);
  updateControls();
  try {
    await api('/api/action', {command, method, settings: settings(), target_keys: [...selected]});
    dirty = false;
    if (command === 'stop') {
      state.status.automatic = false;
      notify('Đã yêu cầu dừng. Chờ thao tác hiện tại kết thúc.');
    } else {
      state.status.busy = true;
      state.status.operation = command;
      if (command === 'login') notify(method === 'qr' ? 'Quét mã trên TikTok bằng điện thoại và xác nhận đăng nhập.' : 'Đăng nhập TikTok trong cửa sổ trình duyệt vừa mở.');
    }
  } catch (error) { notify(error.message, true); }
  finally { pending = false; updateControls(); }
}
$('hero-login').addEventListener('click', () => action('login'));
$('empty-login').addEventListener('click', () => action(state?.account?.authenticated ? 'scan' : 'login'));
$('account-refresh').addEventListener('click', () => action('account'));
$('qr-login').addEventListener('click', () => action('login', 'qr'));
$('scan-button').addEventListener('click', () => action('scan'));
$('video-preview').addEventListener('click', () => action('video_preview'));
$('auto-button').addEventListener('click', () => action('auto'));
$('send-button').addEventListener('click', () => action('send'));
$('stop-button').addEventListener('click', () => action('stop'));
$('search').addEventListener('input', renderFriends);
$('streak-filter').addEventListener('change', () => {renderFriends(); updateControls();});
$('select-all').addEventListener('change', () => {
  for (const row of filteredRows().filter(selectableRow)) {
    saveChoice(row.key, $('select-all').checked);
  }
  renderFriends(); updateCounts(); updateControls();
});
window.addEventListener('storage', event => {
  if (!state || (event.key !== selectionProfile && event.key !== null)) return;
  loadExclusions(); syncSelection(); renderFriends(); updateCounts(); updateControls();
});
for (const id of ['message', 'hours','ai-style','video-query']) $(id).addEventListener('input', () => { updatePreview(); scheduleSave(); });
for (const id of ['ai-enabled','daily-mode']) $(id).addEventListener('change', () => { updateControls(); scheduleSave(); });
$('auto-restore').addEventListener('change', () => { syncSelection(); renderFriends(); updateCounts(); updateControls(); scheduleSave(); });
$('browser-select').addEventListener('change', () => { selected.clear(); renderFriends(); updateCounts(); updateControls(); scheduleSave(); });
for (const [id, step] of [['hours-minus', -1], ['hours-plus', 1]]) $(id).addEventListener('click', () => {
  $('hours').value = Math.min(168, Math.max(1, (Number($('hours').value) || 20) + step));
  updatePreview(); scheduleSave();
});
$('help-button').addEventListener('click', () => $('help-dialog').showModal());
$('web-logout').addEventListener('click', async () => {
  try {
    const response = await fetch('/logout', {method: 'POST'});
    if (!response.ok) throw new Error('Chưa đăng xuất được. Vui lòng thử lại.');
    stoppingApp = true;
    location.assign('/login');
  } catch (error) { notify(error.message, true); }
});
for (const id of ['close-help', 'understood']) $(id).addEventListener('click', () => $('help-dialog').close());
$('help-dialog').addEventListener('click', event => { if (event.target === $('help-dialog')) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
$('shutdown-button').addEventListener('click', async () => {
  if (pending) return;
  if (state?.runtime?.mode === 'vps') { await action('stop'); return; }
  try {
    await api('/api/shutdown', {});
    stoppingApp = true; online = false; updateControls();
    $('offline-banner').hidden = false;
    $('offline-banner').textContent = 'Ứng dụng đã tắt. Chạy start.bat khi bạn muốn giữ lửa tiếp nhé.';
    notify('Đã tắt ứng dụng. Bạn có thể đóng tab này.');
  } catch (error) { notify(error.message, true); }
});
document.querySelectorAll('nav .nav-link').forEach(link => link.addEventListener('click', () => {
  document.querySelectorAll('nav .nav-link').forEach(item => item.classList.remove('active'));
  link.classList.add('active');
}));
$('today').textContent = new Date().toLocaleDateString('vi-VN', {weekday: 'long', day: 'numeric', month: 'long'});
updatePreview();
poll();

function renderVideo() {
  const video=state?.video;
  $('video-card').hidden=!video;
  if(!video)return;
  $('video-caption').textContent=video.caption || 'Video giữ chuỗi';
  $('video-duration').textContent=`${video.duration} giây · AI đã kiểm tra mô tả và khung hình`;
  $('video-reason').textContent=video.reason || '';
  if ($('video-cover').getAttribute('src') !== (video.cover || '')) $('video-cover').src=video.cover || '';
  $('video-link').href=video.url;
}
$('ai-test').addEventListener('click',async()=>{
  if(aiTesting)return;aiTesting=true;updateControls();
  $('ai-test-output').hidden=false;$('ai-test-output').textContent='AI đang soạn câu trả lời thử…';
  try {
    const result=await api('/api/ai/draft',{sample:$('ai-sample').value,settings:settings()});
    $('ai-test-output').textContent=result.message;
  } catch(error){$('ai-test-output').textContent=error.message;}
  finally{aiTesting=false;updateControls();}
});
