@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   youtube-text-finder
echo   Search for any text in YouTube videos via OCR
echo ============================================
echo.

REM --- Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python not found. Install Python 3.10+ and add it to PATH.
    echo     https://www.python.org/downloads/
    pause & exit /b 1
)

REM --- Deno (JS runtime for yt-dlp, required since 2025.11.12) ---
where deno >nul 2>nul
if errorlevel 1 (
    echo [*] Deno not found. Installing via winget...
    winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo [!] Failed to install Deno. Download manually: https://deno.land/
        pause & exit /b 1
    )
)

REM --- ffmpeg ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [*] ffmpeg not found. Installing via winget...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo [!] Failed to install ffmpeg.
        pause & exit /b 1
    )
)

REM --- Tesseract OCR ---
where tesseract >nul 2>nul
if errorlevel 1 (
    echo [*] Tesseract not found. Installing via winget...
    winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo [!] Failed to install Tesseract.
        pause & exit /b 1
    )
)

REM --- venv ---
if not exist venv (
    echo [*] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [!] Failed to create venv.
        pause & exit /b 1
    )
)

call venv\Scripts\activate.bat

echo [*] Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo [!] Dependency installation failed.
    pause & exit /b 1
)

echo.
echo ============================================
echo   Starting...
echo ============================================
echo.

REM With arguments: non-interactive CLI mode.
REM Without arguments: interactive menu.
if "%~1"=="" (
    python main.py
) else (
    python main.py %*
)

pause
