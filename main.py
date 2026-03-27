#!/usr/bin/env python3
# ==============================================================================
# OSCAR Robot Simulator - Simulateur de Camera et de Microphone
# ==============================================================================
# Ce programme capture la camera et le microphone de la machine locale
# et les publie en direct vers un serveur LiveKit.
# Il est concu pour fonctionner sur Windows, Linux et Raspberry Pi.
#
# Usage :
#   python main.py                    # Mode interactif (menus et prompts)
#   python main.py --help             # Afficher l'aide
# ==============================================================================

import sys
import os
import platform

# Verification de la version Python minimale requise
if sys.version_info < (3, 9):
    print("Erreur : Python 3.9 ou superieur est requis.")
    print(f"Version detectee : {sys.version}")
    sys.exit(1)


def detect_platform():
    """Detecte la plateforme d'execution et retourne un identifiant lisible."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return "windows"
    elif system == "linux":
        if "arm" in machine or "aarch" in machine:
            return "raspberry_pi"
        return "linux"
    elif system == "darwin":
        return "macos"
    else:
        return "unknown"


def check_dependencies():
    """
    Verifie que toutes les dependances Python sont installees.
    Retourne True si OK, ou affiche les instructions et quitte.
    """
    missing = []
    dependencies = {
        "cv2": "opencv-python",
        "sounddevice": "sounddevice",
        "livekit": "livekit",
        "jwt": "PyJWT",
        "numpy": "numpy"
    }

    for module, package in dependencies.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("\nDependances manquantes detectees :")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\nPour les installer, executez :")
        print(f"  pip install {' '.join(missing)}")
        print("\nOu pour installer toutes les dependances d'un coup :")
        print("  pip install -r requirements.txt")
        current_platform = detect_platform()
        if current_platform in ("linux", "raspberry_pi"):
            print("\nSur Linux / Raspberry Pi, vous avez besoin en plus :")
            print("  sudo apt-get install portaudio19-dev python3-pyaudio libopencv-dev")
        sys.exit(1)


def clear_screen():
    """Efface le terminal selon la plateforme."""
    os.system("cls" if platform.system().lower() == "windows" else "clear")


def print_banner():
    """Affiche la banniere de demarrage du programme."""
    current_platform = detect_platform()
    platform_labels = {
        "windows": "Windows",
        "linux": "Linux",
        "raspberry_pi": "Raspberry Pi",
        "macos": "macOS",
        "unknown": "Plateforme inconnue"
    }

    print("=" * 60)
    print("    OSCAR - Simulateur de Camera et de Microphone")
    print("=" * 60)
    print(f"  Plateforme detectee : {platform_labels.get(current_platform, 'Inconnue')}")
    print(f"  Python              : {sys.version.split()[0]}")
    print("=" * 60)
    print()


def prompt_string(label, default=None, required=True):
    """
    Affiche un prompt propre et retourne la valeur saisie.
    Si stdin est un pipe (non-interactif), ignore les lignes vides et les commentaires (#).
    Si default est fourni, il est affiche et utilise si l'utilisateur n'entre rien.
    """
    import sys

    if default:
        label_display = f"  {label} [defaut: {default}] : "
    else:
        label_display = f"  {label} : "

    is_interactive = sys.stdin.isatty()

    while True:
        print(label_display, end="", flush=True)
        raw = sys.stdin.readline()

        # En mode pipe (non-interactif), on affiche ce qui est lu pour rendre le log lisible
        if not is_interactive:
            print(raw.rstrip())

        # Fin de fichier ou flux ferme
        if not raw:
            if default is not None:
                return default
            elif not required:
                return ""
            else:
                print("    Fin de flux inattendue. Utilisation de la valeur par defaut si disponible.")
                return default or ""

        value = raw.strip()

        # On ignore les lignes vides et les commentaires en mode pipe
        if not is_interactive and (not value or value.startswith("#")):
            continue

        if value:
            return value
        elif default is not None:
            return default
        elif not required:
            return ""
        else:
            print("    Ce champ est obligatoire. Veuillez entrer une valeur.")


def prompt_int(label, default=0, min_val=0, max_val=100):
    """Affiche un prompt numerique avec validation de plage."""
    while True:
        raw = prompt_string(label, str(default))
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            else:
                print(f"    Valeur invalide. Entrez un nombre entre {min_val} et {max_val}.")
        except ValueError:
            print("    Valeur invalide. Entrez un nombre entier.")


def collect_parameters():
    """
    Collecte les parametres de connexion et de capture de maniere interactive.
    Retourne un dictionnaire des parametres confirmes.
    """
    print("ETAPE 1 - Parametres de connexion au serveur LiveKit")
    print("-" * 50)
    print("  Ces informations vous sont fournies par l'administrateur du serveur.")
    print()

    server_url = prompt_string(
        "URL du serveur LiveKit",
        default="wss://stream-livekit.oscar-bot.com"
    )

    print()
    print("  Les cles API se trouvent dans le fichier de configuration du serveur.")
    print("  Format attendu : cle:secret (ex: oscar_prod_key:oscar_super_secret_prod_key)")
    print()

    livekit_keys = prompt_string(
        "Cles API (format cle:secret)",
        required=True
    )

    while ":" not in livekit_keys:
        print("    Format invalide. La valeur doit contenir un ':' separant la cle et le secret.")
        livekit_keys = prompt_string("Cles API (format cle:secret)", required=True)

    api_key, api_secret = [k.strip() for k in livekit_keys.split(":", 1)]

    room_name = prompt_string(
        "Nom de la room",
        default="oscar-lot1-room"
    )

    print()
    print("ETAPE 2 - Identifiant du robot")
    print("-" * 50)
    print("  Choisissez un nom unique pour identifier votre robot dans la room.")
    print("  Exemple : joel, robot-test, alice, dev-lab")
    print("  Ce nom permet au casque de distinguer votre flux des autres.")
    print()

    robot_name = prompt_string("Nom de votre robot", required=True)
    # Nettoyage : on garde uniquement les caracteres alphanumeriques et les tirets
    robot_name = "".join(c if c.isalnum() or c == "-" else "-" for c in robot_name.strip()).lower()
    robot_identity = f"simulateur-robot-{robot_name}"

    print()
    print("ETAPE 3 - Parametres de capture video")
    print("-" * 50)
    print("  Index de camera : 0 = premiere camera, 1 = deuxieme, etc.")
    print()

    camera_index = prompt_int(
        "Index de la camera",
        default=0,
        min_val=0,
        max_val=10
    )

    print()
    print("ETAPE 4 - Parametres de capture audio")
    print("-" * 50)
    print("  Microphone utilise : peripherique par defaut du systeme")

    print()
    print("Recapitulatif des parametres :")
    print("-" * 50)
    print(f"  Serveur LiveKit : {server_url}")
    print(f"  Cle API         : {api_key}")
    print(f"  Room            : {room_name}")
    print(f"  Identifiant     : {robot_identity}")
    print(f"  Camera          : index {camera_index}")
    print(f"  Micro           : peripherique par defaut")
    print()

    confirm = prompt_string("Confirmer ces parametres ? (oui/non)", default="oui")
    if confirm.lower() not in ("oui", "o", "yes", "y"):
        print("Parametres annules. Relancez le programme pour recommencer.")
        sys.exit(0)

    return {
        "server_url": server_url,
        "api_key": api_key,
        "api_secret": api_secret,
        "room_name": room_name,
        "robot_identity": robot_identity,
        "camera_index": camera_index
    }


def check_identity_in_room(params):
    """
    Verifie si un participant avec cet identifiant est deja actif dans la room.

    On interroge l'API REST de LiveKit (endpoint ListParticipants).
    Si le participant est present, il est actuellement connecte et son nom est pris.
    Si la room n'existe pas encore ou si le participant est absent, le nom est libre.

    Note : LiveKit retire automatiquement un participant de la room des qu'il
    se deconnecte. Il n'y a donc aucune donnee residuelle a nettoyer manuellement.
    """
    import urllib.request
    import urllib.error
    import json
    import jwt
    import time

    # Generation d'un token d'administration avec les droits de lecture de la room
    admin_payload = {
        "iss": params["api_key"],
        "sub": "admin-check",
        "nbf": int(time.time()),
        "exp": int(time.time()) + 30,
        "video": {
            "roomAdmin": True,
            "room": params["room_name"]
        }
    }
    admin_token = jwt.encode(admin_payload, params["api_secret"], algorithm="HS256")

    # Construction de l'URL de l'API REST LiveKit
    # L'API utilise HTTPS (wss -> https, ws -> http)
    base_url = params["server_url"].replace("wss://", "https://").replace("ws://", "http://")
    api_url = f"{base_url}/twirp/livekit.RoomService/ListParticipants"

    body = json.dumps({"room": params["room_name"]}).encode("utf-8")
    req = urllib.request.Request(api_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {admin_token}")

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read())
            participants = data.get("participants", [])
            active_identities = [p.get("identity", "") for p in participants]
            return params["robot_identity"] in active_identities
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # La room n'existe pas encore : personne dedans, nom libre
            return False
        # Toute autre erreur HTTP : on suppose que le nom est libre pour ne pas bloquer
        return False
    except Exception:
        # En cas d'erreur reseau ou autre : on laisse passer et on tentera la connexion
        return False


async def test_connectivity(params):
    """
    Teste l'accessibilite du serveur LiveKit avant de lancer le streaming.
    On verifie que le serveur repond sur son endpoint HTTP/HTTPS.
    Retourne True si le serveur est joignable, False sinon.
    """
    import urllib.request
    import urllib.error

    server_url = params["server_url"]
    print()
    print("Test de connectivite en cours...")

    # Conversion de wss:// -> https:// et ws:// -> http:// pour le test HTTP
    test_url = server_url.replace("wss://", "https://").replace("ws://", "http://")
    if not test_url.endswith("/"):
        test_url += "/"

    try:
        req = urllib.request.Request(test_url, method="GET")
        req.add_header("User-Agent", "OSCAR-Simulator/1.0")
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
            if status in (200, 101, 400, 403, 404):
                # 200 = OK, 101 = WebSocket upgrade attendu mais pas fait, 400/403/404 = le serveur repond (meme avec une erreur)
                print(f"Serveur joignable (HTTP {status}).")
                return True
    except urllib.error.HTTPError as e:
        # Un code HTTP d'erreur signifie que le serveur repond quand meme
        print(f"Serveur joignable (HTTP {e.code}).")
        return True
    except urllib.error.URLError as e:
        reason = str(e.reason).lower() if e.reason else ""
        print("\nServeur inaccessible.")
        if "name or service not known" in reason or "getaddrinfo" in reason or "nodename" in reason:
            print("Cause probable : impossible de resoudre l'adresse du serveur.")
            print(f"Verifiez que '{server_url}' est correcte et que vous etes connecte a internet.")
        elif "connection refused" in reason:
            print("Cause probable : le serveur est hors ligne ou le port est bloque.")
        elif "timed out" in reason or "timeout" in reason:
            print("Cause probable : le serveur ne repond pas (timeout).")
            print("Verifiez votre connexion internet et l'etat du serveur.")
        elif "ssl" in reason or "certificate" in reason:
            print("Cause probable : probleme de certificat SSL.")
            print("Verifiez que l'URL commence bien par 'wss://' pour la production.")
        else:
            print(f"Detail : {e}")
        return False
    except Exception as e:
        print(f"\nErreur de connexion inattendue : {e}")
        return False

    return True


async def start_streaming(params):
    """
    Lance le streaming de la camera et du microphone vers le serveur LiveKit.
    Gere les erreurs de capture et de publication.
    """
    import asyncio
    import cv2
    import numpy as np
    import sounddevice as sd
    from livekit import rtc
    import jwt
    import time

    SAMPLE_RATE = 48000
    CHANNELS = 1
    FRAMES_PER_BUFFER = 960

    payload = {
        "iss": params["api_key"],
        "sub": params["robot_identity"],
        "name": params["robot_identity"],
        "nbf": int(time.time()),
        "exp": int(time.time()) + 86400,
        "video": {
            "room": params["room_name"],
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True
        }
    }
    token = jwt.encode(payload, params["api_secret"], algorithm="HS256")

    print()
    print("Connexion a la room en cours...")
    room = rtc.Room()
    try:
        await room.connect(params["server_url"], token)
    except Exception as e:
        print(f"\nErreur de connexion : {e}")
        print("Le streaming ne peut pas demarrer. Verifiez votre connexion et vos parametres.")
        return

    # --- Camera ---
    cap = cv2.VideoCapture(params["camera_index"])
    if not cap.isOpened():
        print(f"\nErreur : impossible d'ouvrir la camera (index {params['camera_index']}).")
        print("Verifiez que votre camera est bien branchee et non utilisee par un autre programme.")
        await room.disconnect()
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    video_source = rtc.VideoSource(1280, 720)
    video_track = rtc.LocalVideoTrack.create_video_track("camera-robot", video_source)
    video_opts = rtc.TrackPublishOptions()
    video_opts.source = rtc.TrackSource.SOURCE_CAMERA

    try:
        await room.local_participant.publish_track(video_track, video_opts)
    except Exception as e:
        print(f"\nErreur de publication video : {e}")
        cap.release()
        await room.disconnect()
        return

    # --- Microphone ---
    audio_source = rtc.AudioSource(SAMPLE_RATE, CHANNELS)
    audio_track = rtc.LocalAudioTrack.create_audio_track("micro-robot", audio_source)
    audio_opts = rtc.TrackPublishOptions()
    audio_opts.source = rtc.TrackSource.SOURCE_MICROPHONE

    try:
        await room.local_participant.publish_track(audio_track, audio_opts)
    except Exception as e:
        print(f"Avertissement : publication audio echouee : {e}")
        print("Le streaming continue avec la video uniquement.")

    print()
    print("Streaming en cours (Ctrl+C pour arreter)")
    print(f"  Room     : {params['room_name']}")
    print(f"  Serveur  : {params['server_url']}")
    print()

    async def capture_audio():
        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()

        def callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(queue.put_nowait, indata.copy())

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=FRAMES_PER_BUFFER,
                callback=callback
            ):
                while True:
                    data = await queue.get()
                    audio_frame = rtc.AudioFrame.create(SAMPLE_RATE, CHANNELS, FRAMES_PER_BUFFER)
                    np.copyto(
                        np.frombuffer(audio_frame.data, dtype=np.int16),
                        data.flatten()
                    )
                    await audio_source.capture_frame(audio_frame)
        except sd.PortAudioError as e:
            print(f"\nErreur microphone : {e}")
            print("Le streaming continue avec la video uniquement.")
        except Exception as e:
            print(f"\nErreur audio inattendue : {e}")

    async def capture_video():
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                print("\nErreur de lecture camera. La camera s'est-elle deconnectee ?")
                break
            frame = cv2.resize(frame, (1280, 720))
            rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            lk_frame = rtc.VideoFrame(1280, 720, rtc.VideoBufferType.RGBA, rgba.tobytes())
            video_source.capture_frame(lk_frame)
            frame_count += 1

            if frame_count % 300 == 0:
                print(f"  {frame_count} frames envoyes...")

            await asyncio.sleep(0.033)

    try:
        await asyncio.gather(capture_video(), capture_audio())
    except KeyboardInterrupt:
        print("\nArret du streaming demande.")
    except Exception as e:
        print(f"\nErreur inattendue pendant le streaming : {e}")
    finally:
        cap.release()
        await room.disconnect()
        print("Deconnecte. A bientot.")


async def run():
    """Point d'entree principal du programme."""
    import asyncio

    check_dependencies()
    clear_screen()
    print_banner()
    params = collect_parameters()

    # Verification du nom de robot avant de lancer le streaming.
    # Si le nom est deja pris par un simulateur actif dans la room,
    # on invite l'utilisateur a en choisir un autre.
    # LiveKit libere automatiquement le nom des qu'un participant se deconnecte,
    # il n'y a donc pas de conflit persistant entre deux sessions.
    print()
    print("Verification du nom de robot en cours...")
    if check_identity_in_room(params):
        print()
        print(f"  Le nom '{params['robot_identity']}' est deja utilise par un simulateur actif dans cette room.")
        print("  Choisissez un nom different pour eviter le conflit.")
        print()

        while True:
            new_name = prompt_string("Nouveau nom de robot", required=True)
            new_name = "".join(c if c.isalnum() or c == "-" else "-" for c in new_name.strip()).lower()
            new_identity = f"simulateur-robot-{new_name}"
            params["robot_identity"] = new_identity

            if not check_identity_in_room(params):
                print(f"  Nom '{new_identity}' disponible.")
                break
            else:
                print(f"  '{new_identity}' est aussi pris. Essayez un autre nom.")
    else:
        print(f"  Nom '{params['robot_identity']}' disponible.")

    connected = await test_connectivity(params)
    if not connected:
        print()
        print("Impossible de demarrer le streaming : la connexion a echoue.")
        print("Corrigez les erreurs ci-dessus et relancez le programme.")
        sys.exit(1)

    await start_streaming(params)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
