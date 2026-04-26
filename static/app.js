/**
 * app.js — общая логика POS-системы
 * Работает на всех страницах
 */

// ── Форматирование валюты ──────────────────────────────────────────────────
function fmt(val) {
  return parseFloat(val || 0).toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }) + ' ₽';
}

// ── API helper ────────────────────────────────────────────────────────────
async function api(url) {
  try {
    const resp = await fetch(url);
    if (resp.status === 401) { window.location.href = '/login'; return null; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (e) {
    console.error('API error:', url, e);
    return null;
  }
}

async function apiReq(method, url, data) {
  return fetch(url, {
    method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
}

// ── Toast-уведомления ─────────────────────────────────────────────────────
function toast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const id = 'toast-' + Date.now();
  const icons = {success: 'check-circle-fill', danger: 'x-circle-fill', warning: 'exclamation-triangle-fill', info: 'info-circle-fill'};
  const html = `
    <div id="${id}" class="toast toast-pos align-items-center text-bg-${type} border-0 show" role="alert">
      <div class="d-flex">
        <div class="toast-body">
          <i class="bi bi-${icons[type] || 'info-circle-fill'} me-2"></i>${message}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    </div>`;
  container.insertAdjacentHTML('beforeend', html);
  setTimeout(() => document.getElementById(id)?.remove(), 4000);
}

// ── Диалог подтверждения ──────────────────────────────────────────────────
function confirmDialog(message, onConfirm, btnText = 'Удалить', btnClass = 'btn-danger') {
  document.getElementById('confirmBody').textContent = message;
  const btn = document.getElementById('confirmOkBtn');
  btn.className = `btn ${btnClass}`;
  btn.textContent = btnText;
  const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
  btn.onclick = () => { modal.hide(); onConfirm(); };
  modal.show();
}

// ── Часы в шапке ─────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('topbar-datetime');
  if (el) {
    const now = new Date();
    el.textContent = now.toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  }
}
setInterval(updateClock, 1000);
updateClock();

// ── Информация о текущем пользователе ────────────────────────────────────
async function loadUserInfo() {
  const me = await api('/api/me');
  if (!me) return;
  const nameEl = document.getElementById('sidebar-username');
  const roleEl = document.getElementById('sidebar-role');
  if (nameEl) nameEl.textContent = me.full_name;
  if (roleEl) roleEl.textContent = me.role === 'admin' ? 'Администратор' : 'Кассир';
}

// ── Выход ──────────────────────────────────────────────────────────────────
async function logout() {
  await apiReq('POST', '/api/logout', {});
  window.location.href = '/login';
}

// ── Статус смены в шапке ──────────────────────────────────────────────────
async function loadShiftStatus() {
  const shift = await api('/api/shifts/active');
  const el = document.getElementById('shift-status');
  if (!el) return;
  if (shift) {
    el.innerHTML = `<span class="badge bg-success"><i class="bi bi-play-fill me-1"></i>Смена открыта с ${shift.opened_at.slice(11,16)}</span>`;
  } else {
    el.innerHTML = `<span class="badge bg-secondary">Смена не открыта</span>`;
  }
}

// ── Переключение сайдбара (мобильная) ────────────────────────────────────
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// ── Инициализация ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadUserInfo();
  loadShiftStatus();
  // Обновляем статус смены каждые 30 сек
  setInterval(loadShiftStatus, 30000);
});
