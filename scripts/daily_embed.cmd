@echo off
rem Daily Gemini embedding run (free tier allows ~1,000 texts per day).
rem Used by the Windows scheduled task "SkillBridge daily embeddings"; safe to run by hand.
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
echo ==== %date% %time% ==== >> data\logs\embed.log
".venv\Scripts\python.exe" -u -m etl.pipeline --only embed >> data\logs\embed.log 2>&1
