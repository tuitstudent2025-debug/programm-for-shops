@echo off
chcp 65001 > nul
echo ================================================
echo   POS-система — запуск
echo ================================================
echo.

REM Проверяем наличие Python
python --version > nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не установлен или не добавлен в PATH
    echo Скачайте Python с https://python.org/downloads
    pause
    exit /b 1
)

REM Устанавливаем зависимости если не установлены
echo Проверка зависимостей...
pip show flask > nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -r requirements.txt
)

echo.
echo Запуск POS-системы...
echo Браузер откроется автоматически через 2 секунды
echo Для остановки нажмите Ctrl+C
echo.
python app.py
pause
