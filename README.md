# OSCAR - Simulateur Robot (Camera + Microphone)


Il est concu pour etre simple a utiliser par n'importe qui, y compris des personnes sans experience technique.

---

## Lancement rapide avec les parametres par defaut

Pour demarrer le simulateur sans saisir les parametres manuellement.

**Sur Windows — double-cliquez sur `lancer_defaut.bat`**

Ou depuis un terminal `cmd.exe` (pas PowerShell) :
```cmd
lancer_defaut.bat
```

**Sur Linux / Raspberry Pi / macOS :**
```bash
chmod +x lancer_defaut.sh
./lancer_defaut.sh
```

> Les parametres par defaut sont dans `reponses_defaut.txt`. Modifiez-les si vos cles API ou votre room changent.


## Compatibilite

| Systeme | Support |
|---|---|
| Windows 10 / 11 | Complet |
| Ubuntu / Debian (Linux) | Complet |
| Raspberry Pi 3 / 4 / 5 | Complet |
| macOS | Complet |

---

## Installation

### Sur Windows

1. Assurez-vous d'avoir Python 3.9 ou superieur installe : https://www.python.org/downloads/
2. Double-cliquez sur le fichier `install.bat`
3. Attendez la fin de l'installation

### Sur Linux ou Raspberry Pi

1. Ouvrez un terminal
2. Rendez le script executable et lancez-le :

```bash
chmod +x install.sh
./install.sh
```

### Sur macOS

```bash
brew install portaudio
pip install -r requirements.txt
```

---

## Lancement

### Sur Windows

```cmd
python main.py
```

### Sur Linux / Raspberry Pi / macOS

```bash
python3 main.py
```

Le programme demarre un menu interactif qui vous guide etape par etape.

---

## Deroulement du lancement

Au premier lancement, le programme vous demande :

1. **L'URL du serveur LiveKit** : l'adresse du serveur fournie par l'administrateur (ex: `wss://stream-livekit.oscar-bot.com`)
2. **Les cles API** : au format `cle:secret`, fournies par l'administrateur
3. **Le nom de la room** : la salle dans laquelle vous souhaitez entrer (ex: `oscar-lot1-room`)
4. **L'index de la camera** : `0` pour la premiere camera, `1` pour la deuxieme, etc.

Puis le programme :
- Affiche un recapitulatif
- Vous demande de confirmer
- Teste la connexion au serveur avant de demarrer
- Lance le streaming si la connexion est reussie

---

## Gestion des erreurs

Le programme identifie et explique clairement les erreurs les plus courantes :

| Situation | Message affiche |
|---|---|
| Cles API incorrectes | "Verifiez vos cles API et le secret" |
| Serveur inaccessible | "Impossible de resoudre l'adresse du serveur" |
| Serveur eteint | "Le serveur est hors ligne ou le port est bloque" |
| Timeout reseau | "Le serveur ne repond pas" |
| Camera non trouvee | "Verifiez que votre camera est bien branchee" |
| Probleme SSL | "Verifiez que l'URL commence bien par wss://" |

---

## Architecture

```
[Votre machine]
  Camera (OpenCV) -------> VideoSource --> LiveKit Room
  Microphone (sounddevice) -> AudioSource ->
                                              |
                              [Casque VR / Navigateur]
                                   subscribes
```

---

## Fichiers du projet

```
simulateur-robot/
    main.py          - Programme principal (lancez ce fichier)
    requirements.txt - Liste des dependances Python
    install.bat      - Installation automatique Windows
    install.sh       - Installation automatique Linux / Raspberry Pi
    .env.example     - Exemple de fichier de configuration
    README.md        - Ce fichier
```

---

## Notes pour Raspberry Pi

Si la camera ne s'ouvre pas sur Raspberry Pi, activez-la depuis la configuration systeme :

```bash
sudo raspi-config
# Interface Options -> Camera -> Enable
sudo reboot
```

Pour les cameras USB classiques, aucune configuration supplementaire n'est necessaire.
