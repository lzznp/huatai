@echo off
chcp 65001 >nul
cd /d "D:\画台"
python "tests\exp_smart_brush3.py" %*
if errorlevel 1 (
  echo.
  echo ============================================================
  echo  Something failed. The message above is the reason.
  echo  Copy it back to the assistant if you are not sure.
  echo ============================================================
  pause
)
