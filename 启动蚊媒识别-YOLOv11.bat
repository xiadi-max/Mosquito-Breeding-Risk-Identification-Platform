@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
title MosquitoMapper YOLO11 Local Trial

set "BACKEND_ROOT=%~dp0backend"
set "START_SCRIPT=%BACKEND_ROOT%\scripts\start_yolo11.ps1"
set "CONDA_ACTIVATE=D:\Anaconda3\Scripts\activate.bat"
set "PYTHON_EXE=D:\Anaconda3\envs\mosquito311-yolov11\python.exe"
set "YOLO_CONFIG_DIR=%BACKEND_ROOT%\runtime\yolo11_config"
set "READY_URL=http://127.0.0.1:8011/api/v1/health/ready"
set "PAGE_URL=http://127.0.0.1:8011/"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ========================================
echo  MosquitoMapper YOLO11 Local Launcher
echo ========================================
echo.

if not exist "%BACKEND_ROOT%" (
    echo [ERROR] Backend directory not found: %BACKEND_ROOT%
    goto :failed
)

if not exist "%START_SCRIPT%" (
    echo [ERROR] YOLO11 start script not found: %START_SCRIPT%
    goto :failed
)

if not exist "%CONDA_ACTIVATE%" (
    echo [ERROR] Conda activation script not found: %CONDA_ACTIVATE%
    goto :failed
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] mosquito311-yolov11 Python not found: %PYTHON_EXE%
    echo Create the environment before using this launcher.
    goto :failed
)

if not exist "%YOLO_CONFIG_DIR%" mkdir "%YOLO_CONFIG_DIR%" >nul 2>nul

echo [1/3] Activating mosquito311-yolov11...
call "%CONDA_ACTIVATE%" mosquito311-yolov11
if errorlevel 1 (
    echo [ERROR] Failed to activate mosquito311-yolov11.
    goto :failed
)

if /i "%~1"=="--check" (
    "%PYTHON_EXE%" -c "import ultralytics; assert ultralytics.__version__ == '8.4.117'; print('[CHECK PASSED] Python and Ultralytics 8.4.117 are available.')"
    if errorlevel 1 goto :failed
    exit /b 0
)

echo [2/3] Starting YOLO11 API and Worker on port 8011...
echo [3/3] The browser will open after the readiness check passes.
echo.
echo Keep this window open. Press Ctrl+C here to stop the services.
echo.

start "" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "$readyUrl='%READY_URL%'; $pageUrl='%PAGE_URL%'; $deadline=(Get-Date).AddSeconds(120); while((Get-Date) -lt $deadline){ try { $result=Invoke-RestMethod -Uri $readyUrl -TimeoutSec 2; if($result.status -eq 'ready'){ Start-Process $pageUrl; exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1"

cd /d "%BACKEND_ROOT%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%" -PythonPath "%PYTHON_EXE%"
set "START_EXIT=%ERRORLEVEL%"

echo.
if "%START_EXIT%"=="0" (
    echo MosquitoMapper YOLO11 has stopped.
) else (
    echo [ERROR] MosquitoMapper YOLO11 exited with code %START_EXIT%.
)
pause
exit /b %START_EXIT%

:failed
echo.
echo Startup check failed. Keep this window open and review the error above.
pause
exit /b 1
