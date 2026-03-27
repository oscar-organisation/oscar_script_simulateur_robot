# OSCAR - Simulateur Robot (Camera + Microphone)

Ce programme capture la camera et le microphone de votre machine et les publie en direct vers le serveur LiveKit OSCAR, permettant a un casque VR ou a n'importe quel client de voir et d'entendre votre flux en temps reel.

Il est concu pour etre simple a utiliser, y compris pour des personnes sans experience technique.

---

## Guide complet pour debuter

Si c'est votre premiere utilisation, lisez en priorite le guide detaille :

**[Guide de demarrage rapide](docs/guide-demarrage-rapide.md)** - installation pas a pas, troubleshooting, notes Raspberry Pi

---

## Lancement rapide (pour les membres de l'equipe OSCAR)

Les parametres de connexion sont deja pre-configures dans `reponses_defaut.txt`.

**Windows** - double-cliquez sur `lancer_defaut.bat`

**Linux / Raspberry Pi :**
```bash
chmod +x lancer_defaut.sh
./lancer_defaut.sh
```

---

## Installation

### Windows

Double-cliquez sur `install.bat`.

### Linux / Raspberry Pi / macOS

```bash
chmod +x install.sh
./install.sh
```

Sur macOS uniquement :
```bash
brew install portaudio
pip3 install -r requirements.txt
```

---

## Lancement interactif

**Windows :**
```cmd
python main.py
```

**Linux / Raspberry Pi / macOS :**
```bash
python3 main.py
```

Le programme vous guidera etape par etape pour configurer votre connexion.

---

## Compatibilite

| Systeme | Support |
|---|---|
| Windows 10 / 11 | Complet |
| Ubuntu / Debian | Complet |
| Raspberry Pi 3 / 4 / 5 | Complet |
| macOS | Complet |

---

## Fichiers du projet

```
simulateur-robot/
    main.py               - Programme principal
    requirements.txt      - Dependances Python
    install.bat           - Installation Windows
    install.sh            - Installation Linux / Raspberry Pi
    lancer_defaut.bat     - Lancement rapide Windows
    lancer_defaut.sh      - Lancement rapide Linux / Raspberry Pi
    reponses_defaut.txt   - Parametres par defaut (modifiable)
    .env.example          - Exemple de configuration
    docs/
        guide-demarrage-rapide.md  - Guide complet pour debutants
```
