@echo off
title My Agent
cd /d E:\AGENT\agent-lab
call .venv\Scripts\activate.bat
python agent.py
pause
