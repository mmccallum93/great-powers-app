@echo off
echo ============================================
echo   Updating Great Powers Game...
echo ============================================
echo.
cd /d "%~dp0"

echo Step 1: Saving changes to GitHub...
git add .
git commit -m "Game update"
git push
echo.

echo Step 2: Deploying to Vercel...
vercel deploy --prod
echo.

echo ============================================
echo   Done! Great Powers Game is updated.
echo ============================================
echo.
pause
