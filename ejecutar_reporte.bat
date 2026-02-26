@echo off
REM ============================================
REM Control Diario de Tareo - Ejecucion 7:00 AM
REM Revisa tareo del dia anterior y envia reporte
REM ============================================

cd /d "%~dp0"

echo [%date% %time%] Iniciando Control de Tareo Diario >> logs\ejecucion.log

REM Ejecutar el orquestador principal (revisa ayer + notifica + reporta)
python main.py >> logs\ejecucion.log 2>&1

echo [%date% %time%] Ejecucion finalizada >> logs\ejecucion.log
echo. >> logs\ejecucion.log
