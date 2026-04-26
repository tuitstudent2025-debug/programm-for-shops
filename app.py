"""
POS-система для малого бизнеса
Запуск: python app.py
Затем откройте браузер: http://127.0.0.1:5000
"""

import sqlite3
import os
import json
import csv
import io
import logging
import shutil
import threading
import webbrowser
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, request, jsonify, session, redirect, url_for,
    render_template, send_file, Response
)
from werkzeug.security import generate_password_hash, check_password_hash

# ─── Инициализация приложения ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pos-secret-key-2024-change-in-prod')
app.config['SESSION_COOKIE_HTTPONLY'] = True

DB_PATH = os.path.join(os.path.dirname(__file__), 'pos.db')

# Настройка логирования
logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), 'pos.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ─── Работа с базой данных ─────────────────────────────────────────────────
def get_db():
    """Получить соединение с БД."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Инициализация БД и заполнение демо-данными."""
    conn = get_db()
    c = conn.cursor()

    # Таблица пользователей
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cashier',
            full_name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Категории товаров
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    # Товары
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            price REAL NOT NULL DEFAULT 0,
            cost_price REAL DEFAULT 0,
            vat_rate INTEGER DEFAULT 0,
            barcode TEXT,
            unit TEXT DEFAULT 'шт',
            stock_quantity REAL DEFAULT 0,
            min_stock REAL DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)

    # Смены
    c.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cashier_id INTEGER REFERENCES users(id),
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            initial_cash REAL DEFAULT 0,
            final_cash_expected REAL DEFAULT 0,
            final_cash_actual REAL DEFAULT 0,
            status TEXT DEFAULT 'open'
        )
    """)

    # Продажи
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER REFERENCES shifts(id),
            cashier_id INTEGER REFERENCES users(id),
            sale_date TEXT NOT NULL,
            total_amount REAL NOT NULL DEFAULT 0,
            discount_amount REAL DEFAULT 0,
            final_amount REAL NOT NULL DEFAULT 0,
            payment_method TEXT DEFAULT 'cash',
            paid_amount REAL DEFAULT 0,
            change_amount REAL DEFAULT 0,
            loyalty_card TEXT,
            is_return INTEGER DEFAULT 0,
            original_sale_id INTEGER,
            note TEXT
        )
    """)

    # Позиции продажи
    c.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER REFERENCES sales(id),
            product_id INTEGER REFERENCES products(id),
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL
        )
    """)

    # Движения товаров
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id),
            movement_type TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL DEFAULT 0,
            document_number TEXT,
            created_at TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id)
        )
    """)

    # Настройки
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Карты лояльности
    c.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_number TEXT UNIQUE NOT NULL,
            discount_percent REAL DEFAULT 5,
            customer_name TEXT,
            phone TEXT
        )
    """)

    # Быстрые кнопки
    c.execute("""
        CREATE TABLE IF NOT EXISTS favorite_buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id),
            sort_order INTEGER DEFAULT 0
        )
    """)

    conn.commit()

    # ── Демо-данные (только если БД пустая) ──
    user_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        # Пользователи
        c.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
                  ('admin', generate_password_hash('admin'), 'admin', 'Администратор'))
        c.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
                  ('кассир', generate_password_hash('1234'), 'cashier', 'Иванова Мария'))

        # Категории
        for cat in ['Напитки', 'Снэки', 'Молочная продукция', 'Хлеб и выпечка', 'Кондитерские изделия']:
            c.execute("INSERT INTO categories (name) VALUES (?)", (cat,))

        # Товары
        demo_products = [
            ('001', 'Вода минеральная 0.5л', 1, 50.0, 25.0, 20, '4607031760238', 'шт', 100, 10),
            ('002', 'Кока-Кола 0.5л', 1, 90.0, 45.0, 20, '5449000000439', 'шт', 50, 5),
            ('003', 'Чипсы Lays 150г', 2, 120.0, 60.0, 20, '4606272010151', 'шт', 30, 5),
            ('004', 'Молоко 1л 3.2%', 3, 85.0, 50.0, 10, '4601234567890', 'шт', 40, 10),
            ('005', 'Хлеб белый нарезной', 4, 55.0, 30.0, 10, '4607031760001', 'шт', 20, 5),
            ('006', 'Шоколад Alpen Gold 100г', 5, 110.0, 60.0, 20, '7622210967978', 'шт', 25, 5),
            ('007', 'Сок Добрый 1л', 1, 95.0, 50.0, 20, '4601234500001', 'шт', 35, 5),
            ('008', 'Кефир 500мл', 3, 65.0, 35.0, 10, '4601234500002', 'шт', 30, 5),
        ]
        for p in demo_products:
            c.execute("""
                INSERT INTO products (article, name, category_id, price, cost_price, vat_rate, barcode, unit, stock_quantity, min_stock, is_favorite)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (*p, 1 if p[0] in ('001','002','003','004') else 0))

        # Настройки по умолчанию
        defaults = {
            'shop_name': 'Мой Магазин',
            'shop_address': 'г. Москва, ул. Примерная, д. 1',
            'shop_inn': '123456789012',
            'shop_phone': '+7 (999) 000-00-00',
            'receipt_footer': 'Спасибо за покупку! Приходите ещё!',
            'use_vat': '0',
            'allow_price_change': '0',
            'return_days': '14',
            'receipt_format': 'full',
            'barcode_prefix': '',
            'barcode_suffix': '',
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v))

        conn.commit()
        logger.info("База данных инициализирована с демо-данными")

    conn.close()


# ─── Декораторы авторизации ────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Требуется авторизация'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Недостаточно прав'}), 403
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


# ─── Вспомогательные функции ───────────────────────────────────────────────
def get_setting(key, default=''):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_active_shift():
    conn = get_db()
    shift = conn.execute(
        "SELECT * FROM shifts WHERE status='open' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(shift) if shift else None


# ─── Страницы (HTML) ────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    if session.get('role') == 'cashier':
        return redirect(url_for('cashier_page'))
    return redirect(url_for('dashboard_page'))


@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/cashier')
@login_required
def cashier_page():
    return render_template('cashier.html')


@app.route('/dashboard')
@login_required
def dashboard_page():
    return render_template('base.html', page='dashboard')


@app.route('/products')
@login_required
@admin_required
def products_page():
    return render_template('products.html')


@app.route('/categories')
@login_required
@admin_required
def categories_page():
    return render_template('categories.html')


@app.route('/inventory')
@login_required
@admin_required
def inventory_page():
    return render_template('inventory.html')


@app.route('/sales-history')
@login_required
def sales_history_page():
    return render_template('sales_history.html')


@app.route('/reports')
@login_required
@admin_required
def reports_page():
    return render_template('reports.html')


@app.route('/settings')
@login_required
@admin_required
def settings_page():
    return render_template('settings.html')


@app.route('/users')
@login_required
@admin_required
def users_page():
    return render_template('users.html')


@app.route('/receipt/<int:sale_id>')
@login_required
def receipt_page(sale_id):
    conn = get_db()
    sale = conn.execute("""
        SELECT s.*, u.full_name as cashier_name
        FROM sales s JOIN users u ON s.cashier_id=u.id
        WHERE s.id=?
    """, (sale_id,)).fetchone()
    if not sale:
        conn.close()
        return "Чек не найден", 404
    items = conn.execute("""
        SELECT si.*, p.name as product_name, p.vat_rate
        FROM sale_items si JOIN products p ON si.product_id=p.id
        WHERE si.sale_id=?
    """, (sale_id,)).fetchall()
    conn.close()
    settings = {}
    conn2 = get_db()
    for row in conn2.execute("SELECT key, value FROM settings").fetchall():
        settings[row['key']] = row['value']
    conn2.close()
    return render_template('receipt.html', sale=dict(sale),
                           items=[dict(i) for i in items], settings=settings)


# ─── API: Авторизация ──────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username,)
    ).fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['full_name'] = user['full_name']
        logger.info(f"Вход: {username} ({user['role']})")
        return jsonify({'success': True, 'role': user['role'], 'full_name': user['full_name']})
    return jsonify({'error': 'Неверный логин или пароль'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    logger.info(f"Выход: {session.get('username')}")
    session.clear()
    return jsonify({'success': True})


@app.route('/api/me')
@login_required
def api_me():
    return jsonify({
        'id': session['user_id'],
        'username': session['username'],
        'role': session['role'],
        'full_name': session['full_name']
    })


# ─── API: Категории ────────────────────────────────────────────────────────
@app.route('/api/categories', methods=['GET'])
@login_required
def api_categories_get():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/categories', methods=['POST'])
@login_required
@admin_required
def api_categories_post():
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Название не может быть пустым'}), 400
    conn = get_db()
    try:
        c = conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        conn.commit()
        cat_id = c.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Категория с таким названием уже существует'}), 409
    conn.close()
    return jsonify({'id': cat_id, 'name': name}), 201


@app.route('/api/categories/<int:cat_id>', methods=['PUT'])
@login_required
@admin_required
def api_categories_put(cat_id):
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Название не может быть пустым'}), 400
    conn = get_db()
    conn.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
@login_required
@admin_required
def api_categories_delete(cat_id):
    conn = get_db()
    # Проверяем наличие товаров в категории
    count = conn.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (cat_id,)).fetchone()[0]
    if count > 0:
        conn.close()
        return jsonify({'error': f'В категории есть {count} товаров. Сначала переместите их.'}), 400
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ─── API: Товары ───────────────────────────────────────────────────────────
@app.route('/api/products', methods=['GET'])
@login_required
def api_products_get():
    conn = get_db()
    rows = conn.execute("""
        SELECT p.*, c.name as category_name
        FROM products p LEFT JOIN categories c ON p.category_id=c.id
        WHERE p.is_active=1
        ORDER BY p.name
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/products/search', methods=['GET'])
@login_required
def api_products_search():
    q = request.args.get('q', '').strip()
    barcode = request.args.get('barcode', '').strip()
    conn = get_db()
    if barcode:
        rows = conn.execute("""
            SELECT p.*, c.name as category_name
            FROM products p LEFT JOIN categories c ON p.category_id=c.id
            WHERE p.barcode=? AND p.is_active=1
        """, (barcode,)).fetchall()
    elif q:
        pattern = f'%{q}%'
        rows = conn.execute("""
            SELECT p.*, c.name as category_name
            FROM products p LEFT JOIN categories c ON p.category_id=c.id
            WHERE (p.name LIKE ? OR p.article LIKE ?) AND p.is_active=1
            LIMIT 20
        """, (pattern, pattern)).fetchall()
    else:
        rows = []
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/products', methods=['POST'])
@login_required
@admin_required
def api_products_post():
    data = request.get_json()
    conn = get_db()
    try:
        c = conn.execute("""
            INSERT INTO products (article, name, category_id, price, cost_price, vat_rate,
                barcode, unit, stock_quantity, min_stock, is_favorite)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get('article', '').strip(),
            data.get('name', '').strip(),
            data.get('category_id') or None,
            float(data.get('price', 0)),
            float(data.get('cost_price', 0)),
            int(data.get('vat_rate', 0)),
            data.get('barcode', '').strip() or None,
            data.get('unit', 'шт'),
            float(data.get('stock_quantity', 0)),
            float(data.get('min_stock', 0)),
            int(data.get('is_favorite', 0))
        ))
        conn.commit()
        pid = c.lastrowid
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({'error': 'Артикул уже существует'}), 409
    conn.close()
    logger.info(f"Добавлен товар ID={pid} [{data.get('article')}] {data.get('name')}")
    return jsonify({'id': pid}), 201


@app.route('/api/products/<int:pid>', methods=['PUT'])
@login_required
@admin_required
def api_products_put(pid):
    data = request.get_json()
    conn = get_db()
    conn.execute("""
        UPDATE products SET article=?, name=?, category_id=?, price=?, cost_price=?,
            vat_rate=?, barcode=?, unit=?, stock_quantity=?, min_stock=?, is_favorite=?
        WHERE id=?
    """, (
        data.get('article', '').strip(),
        data.get('name', '').strip(),
        data.get('category_id') or None,
        float(data.get('price', 0)),
        float(data.get('cost_price', 0)),
        int(data.get('vat_rate', 0)),
        data.get('barcode', '').strip() or None,
        data.get('unit', 'шт'),
        float(data.get('stock_quantity', 0)),
        float(data.get('min_stock', 0)),
        int(data.get('is_favorite', 0)),
        pid
    ))
    conn.commit()
    conn.close()
    logger.info(f"Изменён товар ID={pid}")
    return jsonify({'success': True})


@app.route('/api/products/<int:pid>', methods=['DELETE'])
@login_required
@admin_required
def api_products_delete(pid):
    conn = get_db()
    conn.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    logger.info(f"Деактивирован товар ID={pid}")
    return jsonify({'success': True})


@app.route('/api/products/favorites', methods=['GET'])
@login_required
def api_favorites_get():
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.name, p.price, p.stock_quantity, fb.sort_order
        FROM favorite_buttons fb JOIN products p ON fb.product_id=p.id
        WHERE p.is_active=1
        ORDER BY fb.sort_order
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/products/import-csv', methods=['POST'])
@login_required
@admin_required
def api_products_import_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400
    f = request.files['file']
    content = f.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    conn = get_db()
    imported = 0
    errors = []
    for i, row in enumerate(reader, 1):
        try:
            article = row.get('article', row.get('артикул', '')).strip()
            name = row.get('name', row.get('наименование', '')).strip()
            price = float(row.get('price', row.get('цена', 0)))
            barcode = row.get('barcode', row.get('штрихкод', '')).strip()
            if not article or not name:
                errors.append(f"Строка {i}: пустой артикул или наименование")
                continue
            conn.execute("""
                INSERT OR REPLACE INTO products (article, name, price, barcode)
                VALUES (?,?,?,?)
            """, (article, name, price, barcode or None))
            imported += 1
        except Exception as e:
            errors.append(f"Строка {i}: {str(e)}")
    conn.commit()
    conn.close()
    return jsonify({'imported': imported, 'errors': errors})


# ─── API: Склад/приход ─────────────────────────────────────────────────────
@app.route('/api/inventory', methods=['GET'])
@login_required
def api_inventory_get():
    conn = get_db()
    rows = conn.execute("""
        SELECT im.*, p.name as product_name, p.article, u.full_name as user_name
        FROM inventory_movements im
        JOIN products p ON im.product_id=p.id
        JOIN users u ON im.user_id=u.id
        ORDER BY im.created_at DESC
        LIMIT 200
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inventory', methods=['POST'])
@login_required
@admin_required
def api_inventory_post():
    data = request.get_json()
    items = data.get('items', [])
    doc_number = data.get('document_number', f"ПН-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    movement_type = data.get('movement_type', 'in')
    conn = get_db()
    for item in items:
        pid = item['product_id']
        qty = float(item['quantity'])
        price = float(item.get('price', 0))
        conn.execute("""
            INSERT INTO inventory_movements (product_id, movement_type, quantity, price,
                document_number, created_at, user_id)
            VALUES (?,?,?,?,?,?,?)
        """, (pid, movement_type, qty, price, doc_number, now_str(), session['user_id']))
        if movement_type == 'in':
            conn.execute("UPDATE products SET stock_quantity=stock_quantity+? WHERE id=?", (qty, pid))
        else:
            conn.execute("UPDATE products SET stock_quantity=MAX(0,stock_quantity-?) WHERE id=?", (qty, pid))
    conn.commit()
    conn.close()
    logger.info(f"Движение товаров {movement_type}: {len(items)} позиций, документ {doc_number}")
    return jsonify({'success': True, 'document_number': doc_number}), 201


# ─── API: Смены ────────────────────────────────────────────────────────────
@app.route('/api/shifts/active', methods=['GET'])
@login_required
def api_shifts_active():
    shift = get_active_shift()
    return jsonify(shift)


@app.route('/api/shifts/open', methods=['POST'])
@login_required
def api_shifts_open():
    shift = get_active_shift()
    if shift:
        return jsonify({'error': 'Смена уже открыта'}), 400
    data = request.get_json()
    initial_cash = float(data.get('initial_cash', 0))
    conn = get_db()
    c = conn.execute("""
        INSERT INTO shifts (cashier_id, opened_at, initial_cash, status)
        VALUES (?,?,?,'open')
    """, (session['user_id'], now_str(), initial_cash))
    conn.commit()
    shift_id = c.lastrowid
    conn.close()
    logger.info(f"Открыта смена #{shift_id} кассиром {session['username']}")
    return jsonify({'success': True, 'shift_id': shift_id}), 201


@app.route('/api/shifts/close', methods=['POST'])
@login_required
def api_shifts_close():
    shift = get_active_shift()
    if not shift:
        return jsonify({'error': 'Нет открытой смены'}), 400
    data = request.get_json()
    final_cash_actual = float(data.get('final_cash_actual', 0))
    conn = get_db()
    # Считаем выручку наличными за смену
    cash_total = conn.execute("""
        SELECT COALESCE(SUM(final_amount),0) FROM sales
        WHERE shift_id=? AND payment_method IN ('cash','mixed') AND is_return=0
    """, (shift['id'],)).fetchone()[0]
    expected = shift['initial_cash'] + cash_total
    conn.execute("""
        UPDATE shifts SET closed_at=?, final_cash_expected=?, final_cash_actual=?, status='closed'
        WHERE id=?
    """, (now_str(), expected, final_cash_actual, shift['id']))
    conn.commit()
    # Итоги смены
    totals = conn.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN payment_method='cash' AND is_return=0 THEN final_amount ELSE 0 END),0) as cash,
            COALESCE(SUM(CASE WHEN payment_method='card' AND is_return=0 THEN final_amount ELSE 0 END),0) as card,
            COUNT(CASE WHEN is_return=0 THEN 1 END) as sales_count,
            COUNT(CASE WHEN is_return=1 THEN 1 END) as returns_count,
            COALESCE(SUM(CASE WHEN is_return=0 THEN final_amount ELSE -final_amount END),0) as net_total
        FROM sales WHERE shift_id=?
    """, (shift['id'],)).fetchone()
    conn.close()
    logger.info(f"Закрыта смена #{shift['id']}")
    return jsonify({
        'success': True,
        'cash': totals['cash'],
        'card': totals['card'],
        'sales_count': totals['sales_count'],
        'returns_count': totals['returns_count'],
        'net_total': totals['net_total'],
        'expected': expected,
        'actual': final_cash_actual,
        'difference': final_cash_actual - expected
    })


# ─── API: Продажи ──────────────────────────────────────────────────────────
@app.route('/api/sales', methods=['GET'])
@login_required
def api_sales_get():
    date_from = request.args.get('from', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    date_to = request.args.get('to', datetime.now().strftime('%Y-%m-%d'))
    cashier_id = request.args.get('cashier_id')
    payment = request.args.get('payment')
    conn = get_db()
    query = """
        SELECT s.*, u.full_name as cashier_name
        FROM sales s JOIN users u ON s.cashier_id=u.id
        WHERE DATE(s.sale_date) BETWEEN ? AND ?
    """
    params = [date_from, date_to]
    if cashier_id:
        query += " AND s.cashier_id=?"
        params.append(cashier_id)
    if payment:
        query += " AND s.payment_method=?"
        params.append(payment)
    # Кассир видит только свои продажи
    if session.get('role') == 'cashier':
        query += " AND s.cashier_id=?"
        params.append(session['user_id'])
    query += " ORDER BY s.sale_date DESC LIMIT 500"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/sales', methods=['POST'])
@login_required
def api_sales_post():
    shift = get_active_shift()
    if not shift:
        return jsonify({'error': 'Нет открытой смены. Откройте смену перед продажей.'}), 400
    data = request.get_json()
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'Корзина пуста'}), 400

    conn = get_db()
    # Проверка остатков
    for item in items:
        prod = conn.execute("SELECT * FROM products WHERE id=? AND is_active=1", (item['product_id'],)).fetchone()
        if not prod:
            conn.close()
            return jsonify({'error': f'Товар ID={item["product_id"]} не найден'}), 400
        if prod['stock_quantity'] < item['quantity']:
            conn.close()
            return jsonify({'error': f'Недостаточно товара "{prod["name"]}". В наличии: {prod["stock_quantity"]}'}), 400

    total = sum(float(i['quantity']) * float(i['unit_price']) for i in items)
    discount = float(data.get('discount_amount', 0))
    final = max(0, total - discount)
    paid = float(data.get('paid_amount', final))
    change = max(0, paid - final)

    c = conn.execute("""
        INSERT INTO sales (shift_id, cashier_id, sale_date, total_amount, discount_amount,
            final_amount, payment_method, paid_amount, change_amount, loyalty_card)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        shift['id'], session['user_id'], now_str(),
        total, discount, final,
        data.get('payment_method', 'cash'),
        paid, change,
        data.get('loyalty_card', '') or None
    ))
    sale_id = c.lastrowid

    for item in items:
        qty = float(item['quantity'])
        price = float(item['unit_price'])
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, total_price)
            VALUES (?,?,?,?,?)
        """, (sale_id, item['product_id'], qty, price, qty * price))
        # Списываем со склада
        conn.execute("UPDATE products SET stock_quantity=stock_quantity-? WHERE id=?",
                     (qty, item['product_id']))
        conn.execute("""
            INSERT INTO inventory_movements (product_id, movement_type, quantity, price,
                document_number, created_at, user_id)
            VALUES (?,?,?,?,?,?,?)
        """, (item['product_id'], 'out', qty, price, f'ЧЕК-{sale_id}', now_str(), session['user_id']))

    conn.commit()
    conn.close()
    logger.info(f"Продажа #{sale_id} на {final:.2f} ₽, кассир {session['username']}")
    return jsonify({'success': True, 'sale_id': sale_id, 'change': change}), 201


@app.route('/api/sales/<int:sale_id>', methods=['GET'])
@login_required
def api_sales_detail(sale_id):
    conn = get_db()
    sale = conn.execute("""
        SELECT s.*, u.full_name as cashier_name
        FROM sales s JOIN users u ON s.cashier_id=u.id
        WHERE s.id=?
    """, (sale_id,)).fetchone()
    if not sale:
        conn.close()
        return jsonify({'error': 'Чек не найден'}), 404
    items = conn.execute("""
        SELECT si.*, p.name as product_name, p.article, p.vat_rate
        FROM sale_items si JOIN products p ON si.product_id=p.id
        WHERE si.sale_id=?
    """, (sale_id,)).fetchall()
    conn.close()
    return jsonify({'sale': dict(sale), 'items': [dict(i) for i in items]})


@app.route('/api/sales/<int:sale_id>', methods=['DELETE'])
@login_required
@admin_required
def api_sales_delete(sale_id):
    conn = get_db()
    sale = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not sale:
        conn.close()
        return jsonify({'error': 'Чек не найден'}), 404
    if sale['is_return']:
        conn.close()
        return jsonify({'error': 'Нельзя аннулировать возврат'}), 400
    items = conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
    for item in items:
        conn.execute("UPDATE products SET stock_quantity=stock_quantity+? WHERE id=?",
                     (item['quantity'], item['product_id']))
    conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))
    conn.commit()
    conn.close()
    logger.info(f"Аннулирован чек #{sale_id} администратором {session['username']}")
    return jsonify({'success': True})


@app.route('/api/sales/<int:sale_id>/return', methods=['POST'])
@login_required
def api_sales_return(sale_id):
    return_days = int(get_setting('return_days', '14'))
    conn = get_db()
    sale = conn.execute("SELECT * FROM sales WHERE id=? AND is_return=0", (sale_id,)).fetchone()
    if not sale:
        conn.close()
        return jsonify({'error': 'Исходный чек не найден'}), 404
    sale_date = datetime.strptime(sale['sale_date'], '%Y-%m-%d %H:%M:%S')
    if datetime.now() - sale_date > timedelta(days=return_days):
        conn.close()
        return jsonify({'error': f'Возврат возможен только в течение {return_days} дней'}), 400

    shift = get_active_shift()
    if not shift:
        conn.close()
        return jsonify({'error': 'Нет открытой смены'}), 400

    data = request.get_json()
    item_ids = data.get('item_ids')  # список id позиций для возврата
    items = conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
    if item_ids:
        items = [i for i in items if i['id'] in item_ids]

    total_return = sum(i['total_price'] for i in items)
    c = conn.execute("""
        INSERT INTO sales (shift_id, cashier_id, sale_date, total_amount, discount_amount,
            final_amount, payment_method, paid_amount, change_amount, is_return, original_sale_id)
        VALUES (?,?,?,?,0,?,?,?,0,1,?)
    """, (shift['id'], session['user_id'], now_str(), total_return, total_return,
          sale['payment_method'], total_return, sale_id))
    return_id = c.lastrowid
    for item in items:
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, total_price)
            VALUES (?,?,?,?,?)
        """, (return_id, item['product_id'], item['quantity'], item['unit_price'], item['total_price']))
        conn.execute("UPDATE products SET stock_quantity=stock_quantity+? WHERE id=?",
                     (item['quantity'], item['product_id']))
    conn.commit()
    conn.close()
    logger.info(f"Возврат по чеку #{sale_id}, возвратный чек #{return_id}")
    return jsonify({'success': True, 'return_id': return_id}), 201


# ─── API: Отчёты ───────────────────────────────────────────────────────────
@app.route('/api/reports/sales', methods=['GET'])
@login_required
@admin_required
def api_report_sales():
    date_from = request.args.get('from', datetime.now().strftime('%Y-%m-01'))
    date_to = request.args.get('to', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    rows = conn.execute("""
        SELECT DATE(sale_date) as day,
            COUNT(CASE WHEN is_return=0 THEN 1 END) as sales_count,
            COUNT(CASE WHEN is_return=1 THEN 1 END) as returns_count,
            COALESCE(SUM(CASE WHEN is_return=0 THEN final_amount ELSE 0 END),0) as revenue,
            COALESCE(SUM(CASE WHEN is_return=1 THEN final_amount ELSE 0 END),0) as returned,
            COALESCE(SUM(CASE WHEN is_return=0 THEN discount_amount ELSE 0 END),0) as discounts
        FROM sales
        WHERE DATE(sale_date) BETWEEN ? AND ?
        GROUP BY DATE(sale_date)
        ORDER BY day
    """, (date_from, date_to)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/reports/cashiers', methods=['GET'])
@login_required
@admin_required
def api_report_cashiers():
    date_from = request.args.get('from', datetime.now().strftime('%Y-%m-01'))
    date_to = request.args.get('to', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    rows = conn.execute("""
        SELECT u.full_name, u.username,
            COUNT(CASE WHEN s.is_return=0 THEN 1 END) as sales_count,
            COALESCE(SUM(CASE WHEN s.is_return=0 THEN s.final_amount ELSE 0 END),0) as revenue
        FROM sales s JOIN users u ON s.cashier_id=u.id
        WHERE DATE(s.sale_date) BETWEEN ? AND ?
        GROUP BY u.id
        ORDER BY revenue DESC
    """, (date_from, date_to)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/reports/products', methods=['GET'])
@login_required
@admin_required
def api_report_products():
    date_from = request.args.get('from', datetime.now().strftime('%Y-%m-01'))
    date_to = request.args.get('to', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    rows = conn.execute("""
        SELECT p.name, p.article,
            SUM(si.quantity) as sold_qty,
            SUM(si.total_price) as revenue,
            SUM(si.quantity * p.cost_price) as cost,
            SUM(si.total_price) - SUM(si.quantity * p.cost_price) as profit,
            p.stock_quantity, p.min_stock
        FROM sale_items si
        JOIN products p ON si.product_id=p.id
        JOIN sales s ON si.sale_id=s.id
        WHERE DATE(s.sale_date) BETWEEN ? AND ? AND s.is_return=0
        GROUP BY p.id
        ORDER BY revenue DESC
    """, (date_from, date_to)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/reports/inventory', methods=['GET'])
@login_required
@admin_required
def api_report_inventory():
    low_stock = request.args.get('low_stock', '0') == '1'
    conn = get_db()
    query = """
        SELECT p.*, c.name as category_name
        FROM products p LEFT JOIN categories c ON p.category_id=c.id
        WHERE p.is_active=1
    """
    if low_stock:
        query += " AND p.stock_quantity <= p.min_stock"
    query += " ORDER BY p.name"
    rows = conn.execute(query).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─── API: Настройки ────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
@login_required
def api_settings_get():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})


@app.route('/api/settings', methods=['PUT'])
@login_required
@admin_required
def api_settings_put():
    data = request.get_json()
    conn = get_db()
    for k, v in data.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, str(v)))
    conn.commit()
    conn.close()
    logger.info(f"Настройки обновлены администратором {session['username']}")
    return jsonify({'success': True})


# ─── API: Пользователи ─────────────────────────────────────────────────────
@app.route('/api/users', methods=['GET'])
@login_required
@admin_required
def api_users_get():
    conn = get_db()
    rows = conn.execute("SELECT id, username, role, full_name, active FROM users ORDER BY full_name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/users', methods=['POST'])
@login_required
@admin_required
def api_users_post():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'error': 'Логин и пароль обязательны'}), 400
    conn = get_db()
    try:
        c = conn.execute("""
            INSERT INTO users (username, password_hash, role, full_name, active)
            VALUES (?,?,?,?,1)
        """, (username, generate_password_hash(password),
              data.get('role', 'cashier'), data.get('full_name', username)))
        conn.commit()
        uid = c.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Пользователь с таким логином уже существует'}), 409
    conn.close()
    logger.info(f"Создан пользователь {username}")
    return jsonify({'id': uid}), 201


@app.route('/api/users/<int:uid>', methods=['PUT'])
@login_required
@admin_required
def api_users_put(uid):
    data = request.get_json()
    conn = get_db()
    if data.get('password'):
        conn.execute("""
            UPDATE users SET full_name=?, role=?, active=?, password_hash=? WHERE id=?
        """, (data['full_name'], data['role'], int(data.get('active', 1)),
              generate_password_hash(data['password']), uid))
    else:
        conn.execute("""
            UPDATE users SET full_name=?, role=?, active=? WHERE id=?
        """, (data['full_name'], data['role'], int(data.get('active', 1)), uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@login_required
@admin_required
def api_users_delete(uid):
    if uid == session['user_id']:
        return jsonify({'error': 'Нельзя удалить себя'}), 400
    conn = get_db()
    conn.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ─── API: Карты лояльности ─────────────────────────────────────────────────
@app.route('/api/loyalty', methods=['GET'])
@login_required
def api_loyalty_get():
    q = request.args.get('q', '').strip()
    conn = get_db()
    if q:
        rows = conn.execute("""
            SELECT * FROM loyalty_cards WHERE card_number LIKE ? OR phone LIKE ?
        """, (f'%{q}%', f'%{q}%')).fetchall()
    else:
        rows = conn.execute("SELECT * FROM loyalty_cards ORDER BY customer_name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/loyalty', methods=['POST'])
@login_required
@admin_required
def api_loyalty_post():
    data = request.get_json()
    conn = get_db()
    try:
        c = conn.execute("""
            INSERT INTO loyalty_cards (card_number, discount_percent, customer_name, phone)
            VALUES (?,?,?,?)
        """, (data['card_number'], float(data.get('discount_percent', 5)),
              data.get('customer_name', ''), data.get('phone', '')))
        conn.commit()
        lid = c.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Карта с таким номером уже существует'}), 409
    conn.close()
    return jsonify({'id': lid}), 201


# ─── API: Избранные кнопки ─────────────────────────────────────────────────
@app.route('/api/favorites', methods=['PUT'])
@login_required
@admin_required
def api_favorites_put():
    data = request.get_json()
    product_ids = data.get('product_ids', [])
    conn = get_db()
    conn.execute("DELETE FROM favorite_buttons")
    for i, pid in enumerate(product_ids[:12]):
        conn.execute("INSERT INTO favorite_buttons (product_id, sort_order) VALUES (?,?)", (pid, i))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ─── API: Резервное копирование ────────────────────────────────────────────
@app.route('/api/backup', methods=['GET'])
@login_required
@admin_required
def api_backup_download():
    backup_name = f"pos_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=backup_name)


@app.route('/api/backup', methods=['POST'])
@login_required
@admin_required
def api_backup_restore():
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400
    f = request.files['file']
    backup_path = DB_PATH + '.bak'
    shutil.copy2(DB_PATH, backup_path)
    try:
        f.save(DB_PATH)
        # Проверяем валидность БД
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT COUNT(*) FROM users")
        conn.close()
    except Exception as e:
        shutil.copy2(backup_path, DB_PATH)
        return jsonify({'error': f'Ошибка восстановления: {str(e)}'}), 500
    logger.info(f"База данных восстановлена из резервной копии администратором {session['username']}")
    return jsonify({'success': True})


# ─── Главный блок запуска ──────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    # Открываем браузер через 1.5 секунды после старта
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open('http://127.0.0.1:5000')
    threading.Thread(target=open_browser, daemon=True).start()
    print("=" * 50)
    print("  POS-система запущена!")
    print("  Откройте браузер: http://127.0.0.1:5000")
    print("  Логин: admin / Пароль: admin")
    print("  Кассир: кассир / Пароль: 1234")
    print("=" * 50)
    app.run(host='127.0.0.1', port=5000, debug=False)
