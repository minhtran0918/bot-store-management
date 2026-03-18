@echo off
chcp 65001 >nul
title Bot Store Management

REM Check Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please run install.bat first!
    pause
    exit /b 1
)

REM Check that Playwright is installed
python -c "import playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Setup incomplete. Please run install.bat first!
    pause
    exit /b 1
)

REM Pull latest code
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Git not found, skipping update.
) else (
    echo Updating code...
    git pull
    if %errorlevel% neq 0 (
        echo [WARN] Git pull failed, continuing with current code.
    )
)

REM Show version (last commit)
git log -1 --format="Version: %%h - %%s (%%ci)" 2>nul
echo.

REM Create data directories if they do not exist
if not exist "data" mkdir data
if not exist "data\error" mkdir data\error

python main.py
echo.
pause
