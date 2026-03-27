#!/usr/bin/env bash
# ============================================================
#  Script d'installation - OSCAR Simulateur Robot
#  Compatible : Linux (Ubuntu, Debian) et Raspberry Pi
# ============================================================

echo ""
echo "=================================================="
echo "  OSCAR - Installation du Simulateur Robot"
echo "=================================================="
echo ""

# Detection de la plateforme
MACHINE=$(uname -m)
OS=$(uname -s)

if [ "$OS" != "Linux" ]; then
    echo "Ce script est concu pour Linux et Raspberry Pi."
    echo ""
    echo "Sur macOS, installez manuellement :"
    echo "  brew install portaudio"
    echo "  pip3 install -r requirements.txt"
    exit 1
fi

IS_RPI=false
if [ "$MACHINE" = "armv7l" ] || [ "$MACHINE" = "aarch64" ] || [ "$MACHINE" = "armv6l" ]; then
    IS_RPI=true
    echo "Plateforme detectee : Raspberry Pi ($MACHINE)"
else
    echo "Plateforme detectee : Linux ($MACHINE)"
fi

echo ""

# Verification de Python 3
if ! command -v python3 &>/dev/null; then
    echo "Erreur : Python 3 n'est pas installe."
    echo ""
    echo "Installez-le avec la commande suivante :"
    echo "  sudo apt-get install python3 python3-pip python3-venv"
    exit 1
fi

# Verification de la version Python
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "Python $PYTHON_VERSION detecte."
else
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "inconnu")
    echo "Erreur : Python 3.9 ou superieur est requis."
    echo "Version detectee : $PYTHON_VERSION"
    echo ""
    echo "Sur Raspberry Pi OS Bullseye ou superieur, Python 3.9+ est disponible par defaut."
    echo "Sur une version plus ancienne : sudo apt-get install python3.9"
    exit 1
fi

# Installation des dependances systeme
echo ""
echo "Installation des dependances systeme..."
echo "(Cette etape necessite les droits administrateur. Votre mot de passe Linux peut etre demande.)"
echo ""

if command -v apt-get &>/dev/null; then
    sudo apt-get update -q 2>/dev/null || echo "Avertissement : mise a jour de la liste des paquets impossible. Continuation..."
    sudo apt-get install -y \
        portaudio19-dev \
        python3-dev \
        python3-pip \
        libopencv-dev \
        2>/dev/null || echo "Avertissement : certains paquets n'ont pas pu etre installes. Continuation..."
elif command -v dnf &>/dev/null; then
    sudo dnf install -y portaudio-devel python3-devel 2>/dev/null || true
elif command -v pacman &>/dev/null; then
    sudo pacman -S --noconfirm portaudio python 2>/dev/null || true
else
    echo "Avertissement : gestionnaire de paquets non reconnu."
    echo "Installez manuellement : portaudio19-dev python3-dev"
fi

# Installation des dependances Python
echo ""
echo "Installation des dependances Python..."
python3 -m pip install --upgrade pip --quiet
python3 -m pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "Erreur lors de l'installation des dependances Python."
    echo "Essayez avec les droits administrateur : sudo python3 -m pip install -r requirements.txt"
    exit 1
fi

# Message final
echo ""
echo "=================================================="
echo "  Installation terminee avec succes !"
echo "=================================================="
echo ""

if [ "$IS_RPI" = true ]; then
    echo "NOTES POUR RASPBERRY PI :"
    echo ""
    echo "  Camera USB : aucune configuration supplementaire requise."
    echo "  Camera CSI (nappe plate) : activez-la avec :"
    echo "    sudo raspi-config -> Interface Options -> Camera -> Enable"
    echo "    Puis redemarrez : sudo reboot"
    echo ""
    echo "  Microphone USB : branchez-le avant de lancer le simulateur."
    echo ""
fi

echo "Pour lancer le simulateur :"
echo "  ./lancer_defaut.sh    (parametres par defaut)"
echo "  python3 main.py       (mode interactif)"
echo ""
