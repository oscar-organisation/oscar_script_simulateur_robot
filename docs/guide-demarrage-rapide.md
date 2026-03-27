# Guide d'utilisation - OSCAR Simulateur Robot

Ce guide est destine aux personnes qui n'ont pas l'habitude de la ligne de commande.
Il explique pas a pas comment installer et utiliser le simulateur sur chaque type de machine.

---

## Prerequis materiels

Avant de commencer, assurez-vous d'avoir :

- Une camera (webcam USB, camera integree au PC, ou camera CSI sur Raspberry Pi)
- Un microphone (integre au PC, casque USB, ou micro USB)
- Une connexion internet fonctionnelle

---

## Etape 1 - Installer Python

Python est le langage de programmation utilise par le simulateur. Vous devez avoir Python 3.9 ou une version plus recente.

### Sur Windows

1. Ouvrez votre navigateur et allez sur : https://www.python.org/downloads/
2. Cliquez sur le bouton jaune "Download Python 3.x.x"
3. Lancez le fichier telecharge
4. Cochez la case **"Add Python to PATH"** (tres important)
5. Cliquez sur "Install Now"
6. Attendez la fin de l'installation

Pour verifier que Python est bien installe, ouvrez l'invite de commandes (touche Windows + R, tapez `cmd`, appuyez sur Entree) et tapez :
```
python --version
```
Vous devriez voir quelque chose comme `Python 3.11.9`.

### Sur Ubuntu / Debian (Linux)

Ouvrez un terminal et tapez :
```bash
sudo apt-get update
sudo apt-get install python3 python3-pip
```

Pour verifier :
```bash
python3 --version
```

### Sur Raspberry Pi

Sur Raspberry Pi OS (anciennement Raspbian), Python 3 est generalement deja installe.
Verifiez avec :
```bash
python3 --version
```

Si la version est inferieure a 3.9, mettez a jour le systeme :
```bash
sudo apt-get update && sudo apt-get upgrade
```

---

## Etape 2 - Telecharger le simulateur

### Option A - Avec Git (recommande)

Si Git est installe sur votre machine :
```bash
git clone https://github.com/oscar-organisation/oscar_script_simulateur_robot.git
cd oscar_script_simulateur_robot
```

### Option B - Telechargement manuel

1. Allez sur https://github.com/oscar-organisation/oscar_script_simulateur_robot
2. Cliquez sur le bouton vert "Code"
3. Choisissez "Download ZIP"
4. Decompressez le fichier ZIP
5. Ouvrez le dossier decompresse

---

## Etape 3 - Installer les dependances

Les dependances sont les librairies Python necessaires au fonctionnement du simulateur.

### Sur Windows

Double-cliquez sur le fichier `install.bat` dans le dossier du simulateur.

Une fenetre noire s'ouvre, attendez que l'installation se termine. Vous verrez le message "Installation terminee avec succes" quand c'est fini.

### Sur Linux ou Raspberry Pi

Ouvrez un terminal dans le dossier du simulateur et tapez :
```bash
chmod +x install.sh
./install.sh
```

Votre mot de passe Linux peut etre demande. C'est normal, certaines dependances necessitent les droits administrateur.

---

## Etape 4 - Lancer le simulateur

### Lancement rapide (parametres pre-configures)

**Windows :** double-cliquez sur `lancer_defaut.bat`

**Linux / Raspberry Pi :**
```bash
chmod +x lancer_defaut.sh
./lancer_defaut.sh
```

Les parametres de connexion au serveur OSCAR sont deja configures dans le fichier `reponses_defaut.txt`.

### Lancement interactif (saisie manuelle des parametres)

**Windows (dans l'invite de commandes cmd.exe) :**
```
python main.py
```

**Linux / Raspberry Pi :**
```bash
python3 main.py
```

Le programme vous demandera alors :
1. L'adresse du serveur (URL)
2. Les cles d'acces (fournies par l'administrateur)
3. Le nom de la salle (room)
4. Le numero de votre camera (0 pour la premiere)

---

## Etape 5 - Verifier que ca fonctionne

Une fois le programme lance, vous devriez voir :

```
Streaming en cours (Ctrl+C pour arreter)
  Room     : oscar-lot1-room
  Serveur  : wss://stream-livekit.oscar-bot.com
```

Pour verifier que votre flux est visible, ouvrez un navigateur et allez sur :
https://meet.livekit.io

Entrez l'URL du serveur et le token genere par l'outil `token-generator`.

Pour arreter le simulateur : appuyez sur **Ctrl+C** dans le terminal.

---

## Problemes frequents et solutions

### "Python n'est pas reconnu comme commande"
Python n'est pas dans le PATH. Reinstallez Python en cochant bien "Add Python to PATH".

### "La camera ne s'ouvre pas"
- Verifiez que votre camera n'est pas utilisee par un autre programme (Zoom, Teams, etc.)
- Sur Raspberry Pi avec camera CSI, activez-la via `sudo raspi-config`
- Essayez un index different (1, 2...) si vous avez plusieurs cameras

### "Erreur microphone / PortAudioError"
- Verifiez que votre micro est bien branche
- Sur Linux, installez les dependances audio : `sudo apt-get install portaudio19-dev`
- Le simulateur continuera a fonctionner en video uniquement si le micro echoue

### "Serveur inaccessible"
- Verifiez votre connexion internet
- L'URL du serveur doit commencer par `wss://`
- Verifiez que le serveur OSCAR est bien demarre

### "Dependances manquantes"
Relancez `install.bat` (Windows) ou `./install.sh` (Linux/RPi).

---

## Notes specifiques Raspberry Pi

### Camera CSI (la petite nappe plate qui se branche directement)

Avant d'utiliser la camera CSI avec ce simulateur, activez-la :
```bash
sudo raspi-config
```
Allez dans Interface Options > Camera > Enable, puis redemarrez.

Sur Raspberry Pi 4 avec Raspberry Pi OS Bullseye ou superieur, utilisez `libcamera` :
```bash
sudo apt-get install python3-picamera2
```
Et modifiez l'index de camera a `0` ou `-1` selon votre configuration.

### Camera USB (webcam standard)

Une webcam USB standard fonctionne directement, sans configuration particuliere.
Index habituellement : `0`.

### Performance

Le Raspberry Pi 4 (4Go RAM) gere confortablement le streaming 720p @ 30fps.
Sur Raspberry Pi 3, reduisez la resolution en modifiant les valeurs `1280, 720` dans `main.py` vers `640, 480`.

---

## Outil bonus - Visionneur web (test/viewer/viewer.html)

Ce fichier HTML permet de **voir en direct les flux video et audio** de tous les participants connectes a la room, depuis un simple navigateur web.

### Comment l'utiliser

1. Ouvrez le fichier `test/viewer/viewer.html` dans votre navigateur (double-clic suffit)
2. Renseignez l'URL du serveur et votre token JWT
3. Cliquez sur **Se connecter a la room**
4. La liste des participants apparait automatiquement
5. Cliquez sur un participant pour voir son flux video et entendre son audio

### Ou obtenir un token d'acces

Le token JWT est necessaire pour s'authentifier aupres du serveur LiveKit.
Consultez la documentation officielle du projet OSCAR pour obtenir votre cle d'acces :

**Documentation OSCAR — Acces a la Room :** https://oscar-bot.atlassian.net/wiki/x/AQAS

> Ce lien est aussi accessible directement depuis la page du visionneur, sous le champ "Token JWT".
