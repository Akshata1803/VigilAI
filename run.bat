@echo off
chcp 65001 >nul 2>&1
title Vigil AI - Dark Pattern Detector

echo.
echo  ================================================================
echo    Vigil AI  ^|  Dark Pattern Intelligence
echo    Enterprise-grade AI scanner ^| 9 engines ^| 300+ rules
echo  ================================================================
echo.

:: ── 1. Check Python ────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found.
    echo  Please install Python 3.9+ from https://python.org
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v detected

:: ── 2. Move to backend ─────────────────────────────────────────────
cd /d "%~dp0backend"

:: ── 3. Install Python dependencies ─────────────────────────────────
echo  [1/4] Installing Python dependencies...
pip install -r requirements.txt -q --no-warn-script-location
if %errorlevel% neq 0 (
    echo  [WARN] Some packages failed. Retrying with --user flag...
    pip install -r requirements.txt -q --user
    if %errorlevel% neq 0 (
        echo  [ERROR] Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
)
echo  [OK] Dependencies ready.

:: ── 4. Install Playwright Chromium browser ─────────────────────────
echo  [2/4] Installing Playwright Chromium browser...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo  [WARN] Playwright browser install failed. Scanner will use requests fallback mode.
) else (
    echo  [OK] Playwright Chromium ready.
)

:: ── 5. Train / Verify Machine Learning Model ───────────────────────
echo  [3/4] Verifying Scikit-Learn ML Model...
if not exist "app\models\dp_classifier.pkl" (
    echo  [INFO] Dark Pattern ML model not found. Training now (first-time setup)...
    python train\train_ml_model.py
    if %errorlevel% neq 0 (
        echo  [WARN] ML model training failed. ML engine will be disabled.
    ) else (
        echo  [OK] ML model trained and ready.
    )
) else (
    echo  [OK] ML model found and ready.
)

:: ── 6. Launch ──────────────────────────────────────────────────────
echo  [4/4] Launching Vigil AI server...
echo.
echo  ================================================================
echo    Open your browser at:  http://localhost:5000
echo    Press Ctrl+C to stop the server.
echo  ================================================================
echo.
timeout /t 2 /nobreak >nul
start "" http://localhost:5000
python run.py

echo.
echo  Vigil AI server stopped.
pause
