@echo off
echo ==========================================
echo   BetWise — Starting Docker Compose Stack
echo ==========================================
echo.

docker-compose up -d --build

echo.
echo Waiting for services to be healthy...

:wait_backend
echo   Checking backend...
timeout /t 3 /nobreak >nul
curl -sf http://localhost:2323/api/health >nul 2>&1
if errorlevel 1 goto wait_backend
echo   Backend: ready

:wait_frontend
echo   Checking frontend...
timeout /t 3 /nobreak >nul
curl -sf http://localhost:3000 >nul 2>&1
if errorlevel 1 goto wait_frontend
echo   Frontend: ready

echo.
echo ==========================================
echo   BetWise is running!
echo.
echo   Dashboard: http://localhost:3000/admin
echo   Chat:      http://localhost:3000/chat
echo   API:       http://localhost:2323/api/health
echo ==========================================
