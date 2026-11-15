@echo off
chcp 65001 >nul
title EFVM Ticket Monitor - Vale
cd /d "%~dp0"

echo ======================================================================
echo   🚂 EFVM TICKET MONITOR - TREM DE PASSAGEIROS VALE
echo ======================================================================
echo   Iniciando o monitor em uma nova sessao...
echo.

python efvmTicketSearcher.py

if errorlevel 1 (
    echo.
    echo [!] Ocorreu um erro ao executar o programa.
    echo     Verifique se o Python e as dependencias estao instalados:
    echo     pip install playwright
    echo     playwright install chromium
    echo.
    pause
)
