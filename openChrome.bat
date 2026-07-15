@echo off
REM このファイルは DontTouch フォルダの中に配置して使用すること。
REM %~dp0 はこのbatファイル自身が置かれているフォルダ(=DontTouch)を指すため、
REM PCごとにパスを書き換える必要がない。
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%~dp0" --kiosk-printing --start-maximized
) else (
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%~dp0" --kiosk-printing --start-maximized
)