@echo off
REM ============================================================
REM  Script d'installation - OSCAR Simulateur Robot (Windows)
REM ============================================================
echo Installation du simulateur OSCAR sur Windows...
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Erreur : Python n'est pas installe ou non accessible dans le PATH.
    echo Telechargez Python 3.9+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installation des dependances Python...
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo Erreur lors de l'installation des dependances.
    echo Essayez de relancer en tant qu'administrateur.
    pause
    exit /b 1
)

echo.
echo Installation terminee avec succes.
echo Pour lancer le simulateur : python main.py
echo.
pause
