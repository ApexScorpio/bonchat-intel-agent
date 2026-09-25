@echo off
title BonChat Intelligence Agent - Execucao Manual
color 0B
cls

echo.
echo ========================================================
echo   BonChat Intelligence Agent - Briefing Operacional
echo ========================================================
echo.

set PYTHON=S:\Users\lopes\AppData\Local\Programs\Python\Python310\python.exe
set SCRIPT_DIR=%~dp0

cd /d "%SCRIPT_DIR%"

"%PYTHON%" src/main.py --now

echo.
echo ========================================================
echo   Processamento Concluido!
echo ========================================================
echo.
pause
