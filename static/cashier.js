/**
 * cashier.js — логика рабочего места кассира
 */

// ── Состояние ─────────────────────────────────────────────────────────────
let cart = [];             // [{product_id, name, unit_price, quantity, stock_quantity}]
let currentShift = null;
let loyaltyDiscount = 0;
let loyaltyCard = null;
let currentPayMethod = 'cash';
let lastSaleId = null;
let searchTimeout = null;

// ── Инициализация ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await checkShift();
  await loadQuickProducts();
  // Всегда возвращаем фокус в поле поиска
  setInterval(focusSearch, 2000);
  focusSearch();
});

function focusSearch() {
  const el = document.getElementById('product-search');
  if (el && document.activeElement !== el &&
      !document.querySelector('.modal.show') &&
      !document.querySelector('input:focus:not(#product-search)')) {
    el.focus();
  }
}

// ── Управление сменой ──────────────────────────────────────────────────────
async function checkShift() {
  currentShift = await api('/api/shifts/active');
  renderShiftInfo();
  if (!currentShift) {
    new bootstrap.Modal(document.getElementById('shiftModal')).show();
  }
}

function renderShiftInfo() {
  const el = document.getElementById('shift-info-block');
  if (!el) return;
  if (currentShift) {
    el.innerHTML = `
      <div class="d-flex justify-content-between align-items-center mb-2">
        <strong><i class="bi bi-play-circle text-success me-2"></i>Смена открыта</strong>
        <button class="btn btn-sm btn-outline-warning" onclick="openCloseShiftModal()">
          <i class="bi bi-stop-circle me-1"></i>Закрыть
        </button>
      </div>
      <div class="text-muted" style="font-size:12px">
        С: ${currentShift.opened_at.slice(11,16)}<br>
        Нач. остаток: ${fmt(currentShift.initial_cash)}
      </div>`;
  } else {
    el.innerHTML = `
      <div class="text-center">
        <i class="bi bi-clock text-muted d-block fs-4 mb-2"></i>
        <div class="text-muted mb-3">Смена не открыта</div>
        <button class="btn btn-success w-100" onclick="document.getElementById('shiftModal') && new bootstrap.Modal(document.getElementById('shiftModal')).show()">
          <i class="bi bi-play-circle me-2"></i>Открыть смену
        </button>
      </div>`;
  }
}

async function openShift() {
  const initialCash = parseFloat(document.getElementById('initial-cash').value) || 0;
  const resp = await apiReq('POST', '/api/shifts/open', {initial_cash: initialCash});
  if (resp.ok) {
    bootstrap.Modal.getInstance(document.getElementById('shiftModal')).hide();
    currentShift = await api('/api/shifts/active');
    renderShiftInfo();
    loadShiftStatus();
    toast('Смена открыта', 'success');
    focusSearch();
  } else {
    const d = await resp.json();
    toast(d.error, 'danger');
  }
}

async function openCloseShiftModal() {
  const shift = await api('/api/shifts/active');
  if (!shift) { toast('Нет открытой смены', 'warning'); return; }

  // X-отчёт: текущие данные
  const sales = await api(`/api/sales?from=${shift.opened_at.slice(0,10)}&to=${new Date().toISOString().slice(0,10)}`);
  const cashSales = sales ? sales.filter(s => s.payment_method === 'cash' && !s.is_return) : [];
  const cardSales = sales ? sales.filter(s => s.payment_method === 'card' && !s.is_return) : [];
  const cashTotal = cashSales.reduce((a,s) => a + s.final_amount, 0);
  const cardTotal = cardSales.reduce((a,s) => a + s.final_amount, 0);
  const total = cashTotal + cardTotal;

  document.getElementById('close-shift-body').innerHTML = `
    <h5 class="text-center mb-3">X-отчёт (промежуточный)</h5>
    <table class="table table-sm">
      <tr><td>Чеков продаж:</td><td class="text-end fw-bold">${cashSales.length + cardSales.length}</td></tr>
      <tr><td>Выручка наличными:</td><td class="text-end">${fmt(cashTotal)}</td></tr>
      <tr><td>Выручка безналом:</td><td class="text-end">${fmt(cardTotal)}</td></tr>
      <tr class="table-success"><td><strong>Итого выручка:</strong></td><td class="text-end fw-bold">${fmt(total)}</td></tr>
    </table>
    <hr>
    <h5>Закрытие смены (Z-отчёт)</h5>
    <div class="mb-3">
      <label class="form-label">Фактический остаток в кассе (₽):</label>
      <input type="number" class="form-control form-control-lg" id="final-cash-input" value="${(shift.initial_cash + cashTotal).toFixed(2)}" min="0">
      <div class="text-muted mt-1">Ожидаемый остаток: ${fmt(shift.initial_cash + cashTotal)}</div>
    </div>
  `;
  new bootstrap.Modal(document.getElementById('closeShiftModal')).show();
}

async function confirmCloseShift() {
  const finalCash = parseFloat(document.getElementById('final-cash-input').value) || 0;
  const resp = await apiReq('POST', '/api/shifts/close', {final_cash_actual: finalCash});
  if (resp.ok) {
    const d = await resp.json();
    const diff = d.difference;
    const diffText = diff === 0 ? '<span class="text-success">Совпадает</span>' :
      diff > 0 ? `<span class="text-primary">Излишек: ${fmt(diff)}</span>` :
      `<span class="text-danger">Недостача: ${fmt(Math.abs(diff))}</span>`;

    document.getElementById('close-shift-body').innerHTML = `
      <h5 class="text-center text-success mb-3"><i class="bi bi-check-circle me-2"></i>Z-отчёт: смена закрыта</h5>
      <table class="table">
        <tr><td>Продаж:</td><td class="text-end">${d.sales_count}</td></tr>
        <tr><td>Возвратов:</td><td class="text-end">${d.returns_count}</td></tr>
        <tr><td>Выручка наличными:</td><td class="text-end">${fmt(d.cash)}</td></tr>
        <tr><td>Выручка безналом:</td><td class="text-end">${fmt(d.card)}</td></tr>
        <tr class="table-success"><td><strong>Нетто выручка:</strong></td><td class="text-end fw-bold">${fmt(d.net_total)}</td></tr>
        <tr><td>Ожидаемый остаток:</td><td class="text-end">${fmt(d.expected)}</td></tr>
        <tr><td>Фактический остаток:</td><td class="text-end">${fmt(d.actual)}</td></tr>
        <tr><td>Расхождение:</td><td class="text-end">${diffText}</td></tr>
      </table>`;
    document.getElementById('close-shift-footer').innerHTML = `
      <button class="btn btn-outline-secondary" data-bs-dismiss="modal" onclick="location.reload()">Закрыть</button>
      <button class="btn btn-primary" onclick="window.print()"><i class="bi bi-printer me-1"></i>Печать Z-отчёта</button>`;

    currentShift = null;
    renderShiftInfo();
    loadShiftStatus();
  } else {
    const d = await resp.json();
    toast(d.error, 'danger');
  }
}

// ── Быстрые товары ─────────────────────────────────────────────────────────
async function loadQuickProducts() {
  const prods = await api('/api/products/favorites');
  const grid = document.getElementById('quick-grid');
  const panel = document.getElementById('quick-products');
  if (!prods || !prods.length) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  grid.innerHTML = prods.map(p => `
    <button class="quick-btn" onclick="addToCart(${JSON.stringify(p).replace(/"/g,'&quot;')})" title="${p.name}">
      <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;">${p.name}</div>
      <div style="color:#0d6efd;margin-top:2px;">${fmt(p.price)}</div>
    </button>
  `).join('');
}

// ── Поиск товара ───────────────────────────────────────────────────────────
async function onSearchInput(value) {
  clearTimeout(searchTimeout);
  const dd = document.getElementById('search-dropdown');
  if (value.length < 2) { dd.style.display = 'none'; return; }

  // Проверяем штрихкод (обычно 8-13 символов, только цифры)
  if (/^\d{8,13}$/.test(value.trim())) {
    clearSearch();
    await addByBarcode(value.trim());
    return;
  }

  searchTimeout = setTimeout(async () => {
    const results = await api(`/api/products/search?q=${encodeURIComponent(value)}`);
    if (!results) return;
    if (!results.length) {
      dd.innerHTML = '<div class="search-item text-muted">Товары не найдены</div>';
      dd.style.display = 'block';
      return;
    }
    dd.innerHTML = results.map(p => `
      <div class="search-item" onclick="addToCartById(${JSON.stringify(p).replace(/"/g,'&quot;')})">
        <div class="d-flex justify-content-between">
          <div>
            <strong>${highlight(p.name, value)}</strong>
            <small class="text-muted ms-2">${p.article}</small>
            ${p.barcode ? `<small class="text-muted ms-2">${p.barcode}</small>` : ''}
          </div>
          <div class="text-primary fw-bold">${fmt(p.price)}</div>
        </div>
        <small class="text-muted">На складе: ${p.stock_quantity} ${p.unit}</small>
      </div>
    `).join('');
    dd.style.display = 'block';
  }, 250);
}

function highlight(text, query) {
  const re = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`, 'gi');
  return text.replace(re, '<mark>$1</mark>');
}

async function addByBarcode(barcode) {
  const results = await api(`/api/products/search?barcode=${encodeURIComponent(barcode)}`);
  if (!results || !results.length) {
    toast('Товар со штрихкодом ' + barcode + ' не найден', 'warning');
    return;
  }
  addToCartById(results[0]);
}

function clearSearch() {
  document.getElementById('product-search').value = '';
  document.getElementById('search-dropdown').style.display = 'none';
}

function addToCartById(product) {
  clearSearch();
  addToCart(product);
  focusSearch();
}

// ── Корзина ────────────────────────────────────────────────────────────────
function addToCart(product) {
  const existing = cart.find(i => i.product_id === product.id);
  if (existing) {
    if (existing.quantity + 1 > product.stock_quantity) {
      toast(`Недостаточно товара "${product.name}". В наличии: ${product.stock_quantity}`, 'warning');
      return;
    }
    existing.quantity += 1;
  } else {
    if (product.stock_quantity <= 0) {
      toast(`Товар "${product.name}" отсутствует на складе`, 'warning');
      return;
    }
    cart.push({
      product_id: product.id,
      name: product.name,
      unit_price: product.price,
      quantity: 1,
      stock_quantity: product.stock_quantity,
      unit: product.unit || 'шт'
    });
  }
  renderCart();
  recalc();
}

function removeFromCart(index) {
  cart.splice(index, 1);
  renderCart();
  recalc();
}

function updateQty(index, value) {
  const qty = parseFloat(value) || 0;
  if (qty <= 0) { removeFromCart(index); return; }
  const item = cart[index];
  if (qty > item.stock_quantity) {
    toast(`В наличии только ${item.stock_quantity} ${item.unit}`, 'warning');
    cart[index].quantity = item.stock_quantity;
  } else {
    cart[index].quantity = qty;
  }
  renderCart();
  recalc();
}

function clearCart() {
  if (!cart.length) return;
  cart = [];
  loyaltyCard = null;
  loyaltyDiscount = 0;
  document.getElementById('loyalty-input').value = '';
  document.getElementById('loyalty-info').classList.add('d-none');
  renderCart();
  recalc();
}

function renderCart() {
  const tbody = document.getElementById('cart-body');
  if (!cart.length) {
    tbody.innerHTML = `<tr id="cart-empty"><td colspan="6" class="text-center text-muted py-5">
      <i class="bi bi-cart3 fs-1 d-block mb-2"></i>Корзина пуста</td></tr>`;
    return;
  }
  tbody.innerHTML = cart.map((item, i) => `<tr>
    <td class="text-muted">${i + 1}</td>
    <td>
      <div class="fw-semibold">${item.name}</div>
      <small class="text-muted">Склад: ${item.stock_quantity} ${item.unit}</small>
    </td>
    <td class="price-cell">
      <input type="number" class="cart-qty-price form-control form-control-sm"
        style="width:85px" value="${item.unit_price.toFixed(2)}" min="0" step="0.01"
        onchange="updatePrice(${i}, this.value)">
    </td>
    <td>
      <input type="number" class="qty-input" value="${item.quantity}"
        min="0.001" step="0.001" max="${item.stock_quantity}"
        onchange="updateQty(${i}, this.value)">
    </td>
    <td class="fw-bold">${fmt(item.unit_price * item.quantity)}</td>
    <td>
      <button class="btn btn-sm btn-outline-danger" onclick="removeFromCart(${i})">
        <i class="bi bi-x-lg"></i>
      </button>
    </td>
  </tr>`).join('');
}

function updatePrice(index, value) {
  cart[index].unit_price = parseFloat(value) || 0;
  renderCart();
  recalc();
}

// ── Пересчёт итогов ────────────────────────────────────────────────────────
function recalc() {
  const total = cart.reduce((a, i) => a + i.unit_price * i.quantity, 0);
  const discountType = document.getElementById('discount-type').value;
  let discountVal = parseFloat(document.getElementById('discount-value').value) || 0;

  let discountAmt = 0;
  if (discountType === 'percent') {
    discountAmt = total * discountVal / 100;
  } else {
    discountAmt = Math.min(discountVal, total);
  }

  // Скидка по карте лояльности
  const loyaltyAmt = loyaltyDiscount ? total * loyaltyDiscount / 100 : 0;
  const totalDiscount = Math.min(discountAmt + loyaltyAmt, total);
  const final = Math.max(0, total - totalDiscount);

  document.getElementById('total-sum').textContent = fmt(total);
  document.getElementById('discount-sum').textContent = `- ${fmt(totalDiscount)}`;
  document.getElementById('final-sum').textContent = fmt(final);
}

function getDiscountAmount() {
  const total = cart.reduce((a, i) => a + i.unit_price * i.quantity, 0);
  const discountType = document.getElementById('discount-type').value;
  let discountVal = parseFloat(document.getElementById('discount-value').value) || 0;
  let discountAmt = discountType === 'percent' ? total * discountVal / 100 : Math.min(discountVal, total);
  const loyaltyAmt = loyaltyDiscount ? total * loyaltyDiscount / 100 : 0;
  return Math.min(discountAmt + loyaltyAmt, total);
}

function getFinalAmount() {
  const total = cart.reduce((a, i) => a + i.unit_price * i.quantity, 0);
  return Math.max(0, total - getDiscountAmount());
}

// ── Карта лояльности ──────────────────────────────────────────────────────
let loyaltyTimeout = null;
async function checkLoyalty(value) {
  clearTimeout(loyaltyTimeout);
  if (!value || value.length < 3) {
    clearLoyalty();
    return;
  }
  loyaltyTimeout = setTimeout(async () => {
    const results = await api(`/api/loyalty?q=${encodeURIComponent(value)}`);
    if (results && results.length) {
      const card = results[0];
      loyaltyCard = card.card_number;
      loyaltyDiscount = card.discount_percent;
      const info = document.getElementById('loyalty-info');
      info.innerHTML = `<i class="bi bi-check-circle text-success me-2"></i>
        Карта: <strong>${card.customer_name || card.card_number}</strong>
        — скидка <strong>${card.discount_percent}%</strong>`;
      info.classList.remove('d-none');
      recalc();
    } else {
      clearLoyalty();
    }
  }, 500);
}

function clearLoyalty() {
  loyaltyCard = null;
  loyaltyDiscount = 0;
  document.getElementById('loyalty-info').classList.add('d-none');
  recalc();
}

// ── Оплата ────────────────────────────────────────────────────────────────
function openPayModal(method) {
  if (!currentShift) {
    toast('Откройте смену перед продажей', 'warning');
    return;
  }
  if (!cart.length) {
    toast('Добавьте товары в корзину', 'warning');
    return;
  }

  currentPayMethod = method;
  const final = getFinalAmount();
  const titles = {cash: 'Оплата наличными', card: 'Оплата картой', mixed: 'Смешанная оплата'};
  document.getElementById('pay-modal-title').textContent = titles[method];

  let body = `<div class="mb-3 fs-4 text-center fw-bold">К оплате: <span class="text-primary">${fmt(final)}</span></div>`;

  if (method === 'cash') {
    body += `
      <div class="mb-3">
        <label class="form-label fs-5">Сумма от покупателя (₽)</label>
        <input type="number" class="form-control form-control-lg" id="pay-received"
          value="${Math.ceil(final)}" min="${final}" step="1" oninput="calcChange()">
      </div>
      <div class="fs-4 text-center" id="change-display">
        Сдача: <strong class="text-success" id="change-val">0,00 ₽</strong>
      </div>`;
  } else if (method === 'card') {
    body += `<p class="text-center text-muted"><i class="bi bi-credit-card fs-1 d-block mb-3"></i>Нажмите «Провести», чтобы зафиксировать оплату картой.</p>`;
  } else {
    body += `
      <div class="mb-3">
        <label class="form-label">Оплата наличными (₽)</label>
        <input type="number" class="form-control form-control-lg" id="pay-cash-part"
          value="0" min="0" max="${final}" step="1" oninput="calcMixedChange()">
      </div>
      <div class="mb-3">
        <label class="form-label">Оплата картой (₽)</label>
        <input type="number" class="form-control form-control-lg" id="pay-card-part"
          value="${final}" min="0" max="${final}" step="1" readonly>
      </div>`;
  }

  document.getElementById('pay-modal-body').innerHTML = body;
  if (method === 'cash') setTimeout(calcChange, 50);
  new bootstrap.Modal(document.getElementById('payModal')).show();
  setTimeout(() => document.getElementById('pay-received')?.focus(), 300);
}

function calcChange() {
  const final = getFinalAmount();
  const received = parseFloat(document.getElementById('pay-received')?.value) || 0;
  const change = Math.max(0, received - final);
  const el = document.getElementById('change-val');
  if (el) el.textContent = fmt(change);
}

function calcMixedChange() {
  const final = getFinalAmount();
  const cashPart = parseFloat(document.getElementById('pay-cash-part')?.value) || 0;
  const cardPart = Math.max(0, final - cashPart);
  const el = document.getElementById('pay-card-part');
  if (el) el.value = cardPart.toFixed(2);
}

async function confirmPayment() {
  const final = getFinalAmount();
  let paidAmount = final;
  let changeAmount = 0;

  if (currentPayMethod === 'cash') {
    paidAmount = parseFloat(document.getElementById('pay-received')?.value) || final;
    if (paidAmount < final) { toast('Недостаточная сумма', 'warning'); return; }
    changeAmount = paidAmount - final;
  } else if (currentPayMethod === 'mixed') {
    const cashPart = parseFloat(document.getElementById('pay-cash-part')?.value) || 0;
    paidAmount = final;
    changeAmount = 0;
  }

  const saleData = {
    items: cart.map(i => ({
      product_id: i.product_id,
      quantity: i.quantity,
      unit_price: i.unit_price
    })),
    discount_amount: getDiscountAmount(),
    payment_method: currentPayMethod,
    paid_amount: paidAmount,
    change_amount: changeAmount,
    loyalty_card: loyaltyCard
  };

  const resp = await apiReq('POST', '/api/sales', saleData);
  if (resp.ok) {
    const d = await resp.json();
    lastSaleId = d.sale_id;
    bootstrap.Modal.getInstance(document.getElementById('payModal')).hide();
    showSuccessModal(final, changeAmount, d.sale_id);
    clearCart();
    clearLoyalty();
    document.getElementById('discount-value').value = '0';
    recalc();
  } else {
    const d = await resp.json();
    toast(d.error, 'danger');
  }
}

function showSuccessModal(final, change, saleId) {
  let html = `
    <div class="py-2">
      <div class="fs-2 fw-bold text-success mb-2">${fmt(final)}</div>
      <div class="text-muted">Чек #${saleId}</div>
    </div>`;
  if (currentPayMethod === 'cash' && change > 0) {
    html += `
      <div class="alert alert-success fs-3 fw-bold mt-3">
        <i class="bi bi-cash-stack me-2"></i>Сдача: ${fmt(change)}
      </div>`;
  }
  document.getElementById('change-modal-body').innerHTML = html;
  document.getElementById('print-receipt-btn').onclick = () => {
    window.open(`/receipt/${saleId}`, '_blank', 'width=400,height=700');
  };
  new bootstrap.Modal(document.getElementById('changeModal')).show();
}

function closeChangeModal() {
  const modal = bootstrap.Modal.getInstance(document.getElementById('changeModal'));
  if (modal) modal.hide();
  focusSearch();
}
