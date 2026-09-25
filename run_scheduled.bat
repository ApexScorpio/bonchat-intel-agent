@echo off
title BonChat Intelligence Agent - Agendador (13:30 e 21:30)
color 0E
cls

echo.
echo ========================================================
echo   BonChat Intelligence Agent - Servico Agendado
echo   Horarios de envio: 13:30 e 21:30 diariamente
echo ========================================================
echo.

set PYTHON=S:\Users\lopes\AppData\Local\Programs\Python\Python310\python.exe
set SCRIPT_DIR=%~dp0

cd /d "%SCRIPT_DIR%"

"%PYTHON%" src/main.py --schedule
