@echo off
chcp 65001 >nul
title Bot Store Management - Setup

echo ============================================
echo   Bot Store Management - First-time Setup
echo ============================================
echo.

REM Check Python is installed and available on PATH
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python from https://www.python.org/downloads/windows/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version') do echo [OK] Found %%v

echo.
echo [1/2] Installing Python dependencies...
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed!
    pause
    exit /b 1
)
echo     Dependencies OK

echo.
echo [2/2] Installing Chromium browser for Playwright...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo [ERROR] Chromium installation failed!
    pause
    exit /b 1
)
echo     Chromium OK

echo.
echo ============================================
echo   Setup complete!
echo   You can now run the bot using: run.bat
echo ============================================
echo.
pause
