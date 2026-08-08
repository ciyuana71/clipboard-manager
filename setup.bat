@echo off
chcp 65001 >nul
echo ========================================
echo   剪贴板管理器 - 安装 &amp; 启动
echo ========================================
echo.
echo [1/2] 正在安装依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo 依赖安装失败，请检查 Python 和 pip 是否已正确安装。
    pause
    exit /b 1
)
echo [2/2] 启动剪贴板管理器（无终端窗口）...
start pythonw clipboard_manager.pyw
echo 程序已在后台启动，请查看系统托盘图标。
timeout /t 2 /nobreak >nul
