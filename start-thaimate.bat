@echo off
chcp 65001 >nul
title ThaiMate Launcher
set "ROOT=%~dp0"

echo ===== ThaiMate AI =====

rem 1) ตรวจว่า Ollama ทำงานอยู่ไหม
curl.exe -s http://localhost:11434 >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama ยังไม่ทำงาน กำลังพยายามเปิด...
    start "" ollama serve
    timeout /t 5 /nobreak >nul
)

rem 2) เปิด Backend (FastAPI)
if not exist "%ROOT%backend\venv\Scripts\python.exe" (
    echo [X] ไม่พบ venv ที่ backend\venv ต้องสร้างก่อน ดู README
    pause
    exit /b 1
)
start "ThaiMate Backend" cmd /k "cd /d %ROOT%backend && venv\Scripts\python.exe -m uvicorn main:app"

rem 3) เปิด Frontend (Next.js)
start "ThaiMate Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

rem 4) รอให้เซิร์ฟเวอร์พร้อม แล้วเปิดเบราว์เซอร์
echo รอระบบเริ่มทำงาน...
timeout /t 10 /nobreak >nul
start "" http://localhost:3000

echo.
echo เปิดแล้ว ปิดหน้าต่าง Backend และ Frontend เมื่อเลิกใช้
timeout /t 3 >nul