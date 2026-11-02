@echo off
REM =========================================================
REM Daily PostgreSQL DB Backup Script
REM Save as: C:\Users\natas\Desktop\server-main\myproject\backup.bat
REM
REM ✅ FIX: Pehle ye script SQLite (db.sqlite3) back up kar rahi thi,
REM          lekin production me PostgreSQL use ho raha hai.
REM          Ab pg_dump se proper backup ban raha hai.
REM
REM Prerequisites:
REM   1. PostgreSQL client tools installed (pg_dump PATH me hona chahiye)
REM   2. Neeche credentials .env ke mutabiq set karein
REM =========================================================

setlocal enabledelayedexpansion

set PROJECT_DIR=C:\Users\natas\Desktop\server-main\myproject
set BACKUP_DIR=C:\Backups\rockgames

REM ---------- PostgreSQL Credentials ----------
REM ✅ IMPORTANT: Ye values apni .env file ke DB_* values se match karein
set PGUSER=rockgames_user
set PGPASSWORD=YOUR_DB_PASSWORD_HERE
set PGHOST=127.0.0.1
set PGPORT=5432
set PGDATABASE=rockgames_db

REM ---------- Timestamp ----------
set DATE_STR=%date:~10,4%-%date:~4,2%-%date:~7,2%
set TIME_STR=%time:~0,2%-%time:~3,2%
set TIME_STR=%TIME_STR: =0%

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

echo [%date% %time%] Starting PostgreSQL backup...

REM ---------- PostgreSQL Dump ----------
REM -Fc = custom format (restore easily with pg_restore)
echo [INFO] Dumping PostgreSQL database %PGDATABASE% ...
pg_dump -U %PGUSER% -h %PGHOST% -p %PGPORT% -Fc -f "%BACKUP_DIR%\db_%DATE_STR%_%TIME_STR%.dump" %PGDATABASE%

if errorlevel 1 (
    echo [ERROR] pg_dump FAILED! Backup NOT created.
    echo [ERROR] Check: pg_dump installed? Credentials correct? DB reachable?
    endlocal
    exit /b 1
)

echo [OK] Database dump: %BACKUP_DIR%\db_%DATE_STR%_%TIME_STR%.dump

REM ---------- Media Backup ----------
if exist "%PROJECT_DIR%\media" (
    robocopy "%PROJECT_DIR%\media" "%BACKUP_DIR%\media_%DATE_STR%" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS
    echo [OK] Media backup: %BACKUP_DIR%\media_%DATE_STR%
) else (
    echo [WARN] Media folder not found: %PROJECT_DIR%\media
)

REM ---------- Prune old DB backups (>14 days) ----------
forfiles /p "%BACKUP_DIR%" /m "db_*.dump" /d -14 /c "cmd /c del @path" 2>nul

echo [%date% %time%] Backup complete.
endlocal