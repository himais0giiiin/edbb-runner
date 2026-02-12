@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0edbb-runner.ps1" -dev
pause
