@echo off
rem بات تلگرام — برای Task Scheduler ویندوز.
rem   Trigger: At log on   |   Settings: Restart on failure every 1 minute, up to 99 times
rem   Action: Start a program → این فایل   |   Start in: پوشه پروژه
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist data mkdir data
python -m divar_demo.bot >> data\bot.log 2>&1
