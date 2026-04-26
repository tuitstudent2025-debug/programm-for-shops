#!/bin/bash
echo "================================================"
echo "  POS-система — запуск"
echo "================================================"

# Проверяем Python
if ! command -v python3 &> /dev/null; then
    echo "ОШИБКА: Python 3 не установлен"
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    exit 1
fi

# Устанавливаем зависимости
echo "Проверка зависимостей..."
pip3 show flask &> /dev/null || pip3 install -r requirements.txt

echo ""
echo "Запуск POS-системы на http://127.0.0.1:5000"
echo "Нажмите Ctrl+C для остановки"
echo ""
python3 app.py
