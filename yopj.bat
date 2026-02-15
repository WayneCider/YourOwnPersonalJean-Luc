@echo off
REM YOPJ — Your Own Personal Jean-Luc
REM Launcher script. Place in PATH or run directly.
REM
REM Usage:
REM   yopj --model C:\path\to\model.gguf
REM   yopj --server --port 8080
REM   yopj --model C:\path\to\model.gguf --dangerously-skip-permissions

python "%~dp0yopj.py" %*
