@echo off
setlocal DisableDelayedExpansion
where python >nul 2>nul
if not errorlevel 1 goto use_python
where py >nul 2>nul
if not errorlevel 1 goto use_py
echo [ERROR] Python 3.9+ was not found on PATH. Install it manually.
exit /b 1
:use_python
python "%~dp0start_omnisearch.py" %*
exit /b %errorlevel%
:use_py
py -3 "%~dp0start_omnisearch.py" %*
exit /b %errorlevel%
