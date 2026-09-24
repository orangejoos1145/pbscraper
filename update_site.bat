@echo off
cd /d "%~dp0"

echo Running PB Scraper...
python pbscraper.py

echo Generating PB HTML...
python AIOHtmlGen.py

echo Pushing Updates to GitHub...
git config user.email "creepybone1145@gmail.com"
git config user.name "Harman"

git add .
git commit -m "Automated daily PB update"
git push origin main