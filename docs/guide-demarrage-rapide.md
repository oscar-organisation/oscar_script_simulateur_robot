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

La page `test/viewer/viewer.html` permet de **visualiser en direct les flux video et audio** de tous les simulateurs connectes a la room, depuis un simple navigateur. Aucune installation requise, aucun token a generer manuellement.

### Comment l'ouvrir

Double-cliquez sur le fichier `test/viewer/viewer.html`. Il s'ouvre directement dans votre navigateur.

### Ce que vous voyez dans le formulaire

Les champs sont deja pre-remplis avec les parametres de l'environnement OSCAR. Vous n'avez qu'une seule chose a renseigner :

| Champ | Valeur | Modifiable |
|---|---|---|
| URL du serveur LiveKit | `wss://stream-livekit.oscar-bot.com` | Oui (si serveur different) |
| Nom de la room | `oscar-lot1-room` | Oui (si room differente) |
| Cle API LiveKit | `oscar_prod_key` | Ne pas modifier |
| Secret API LiveKit | (masque) | Ne pas modifier |
| **Nom de l'operateur** | **A remplir** | Oui |
| Token genere | Rempli automatiquement | Non (lecture seule) |

### Pourquoi un nom d'operateur ?

Chaque personne qui ouvre le visionneur doit entrer un prenom ou un identifiant unique (ex: `joel`, `alice`, `operateur-02`). La page genere alors automatiquement un token JWT personnalise avec votre nom comme identifiant. Cela garantit que deux personnes peuvent regarder la room en meme temps sans se deconnecter mutuellement.

### Etapes de connexion

1. Ouvrez `test/viewer/viewer.html` dans votre navigateur
2. Entrez votre nom dans le champ **Nom de l'operateur du casque**
3. Cliquez sur **Se connecter a la room**
4. Le token est genere automatiquement et s'affiche dans le champ lecture seule
5. La liste des simulateurs connectes apparait dans le panneau de gauche
6. Cliquez sur un simulateur pour voir son flux video et entendre son audio en direct
