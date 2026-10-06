@echo off
rem UART echo latency test. No args = GUI. Args are passed through (e.g. run.bat --cli -n 100)
cd /d "%~dp0"
"%~dp0Python3.8.10\python.exe" -m app.main %*
