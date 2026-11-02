@echo off
REM =========================================================
REM Continuous sweeper — runs every 30 seconds
REM Save as: C:\Users\natas\Desktop\server-main\myproject\sweeper_loop.bat
REM =========================================================

cd /d "C:\Users\natas\Desktop\server-main\myproject"

:loop
echo [%date% %time%] Sweeper run...
python manage.py ludo_sweeper
timeout /t 30 /nobreak >nul
goto loop