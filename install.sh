#!/usr/bin/env bash
# ============================================================
#  Script d'installation - OSCAR Simulateur Robot (Linux / Raspberry Pi)
# ============================================================
set -e

echo "Installation du simulateur OSCAR..."
echo ""

# Detection de la plateforme
MACHINE=$(uname -m)
OS=$(uname -s)

if [ "$OS" != "Linux" ]; then
    echo "Ce script est concu pour Linux et Raspberry Pi."
    echo "Sur macOS, utilisez : brew install portaudio && pip install -r requirements.txt"
    exit 1
fi

# Verification de Python
if ! command -v python3 &>/dev/null; then
    echo "Erreur : python3 n'est pas installe."
    echo "Installez-le avec : sudo apt-get install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED="3.9"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"; then
    echo "Python $PYTHON_VERSION detecte."
else
    echo "Erreur : Python 3.9+ requis. Version detectee : $PYTHON_VERSION"
    exit 1
fi

# Installation des dependances systeme (portaudio requis par sounddevice)
echo ""
echo "Installation des dependances systeme (necessaire pour le micro)..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -q
    sudo apt-get install -y portaudio19-dev python3-pyaudio libopencv-dev python3-dev
elif command -v dnf &>/dev/null; then
    sudo dnf install -y portaudio-devel opencv-python3
else
    echo "Gestionnaire de paquets non reconnu. Installez manuellement : portaudio19-dev libopencv-dev"
fi

# Installation des dependances Python
echo ""
echo "Installation des dependances Python..."
pip3 install -r requirements.txt

echo ""
echo "Installation terminee."
if [ "$MACHINE" = "armv7l" ] || [ "$MACHINE" = "aarch64" ]; then
    echo "NOTE Raspberry Pi : si la camera ne fonctionne pas, activez-la avec :"
    echo "  sudo raspi-config -> Interface Options -> Camera -> Enable"
fi
echo ""
echo "Pour lancer le simulateur : python3 main.py"
