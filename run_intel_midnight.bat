@echo off
setlocal
set PYTHON=C:\Users\lopes\AppData\Local\Programs\Python\Python310\python.exe
if not exist "%PYTHON%" set PYTHON=S:\Users\lopes\AppData\Local\Programs\Python\Python310\python.exe
cd /d "%~dp0"
if not exist "logs" mkdir "logs"

echo [%date% %time%] Iniciar Intel Agent - Fecho Diario Meia-Noite >> "logs\intel_midnight.log"
"%PYTHON%" src/main.py --now --shift "FECHO DIARIO (00:00)" >> "logs\intel_midnight.log" 2>&1
echo [%date% %time%] Concluido com codigo %errorlevel% >> "logs\intel_midnight.log"
