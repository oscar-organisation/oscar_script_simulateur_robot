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
    Si default est fourni, il est affiche et utilise si l'utilisateur ne saisit rien.
    """
    if default:
        label_display = f"  {label} [defaut: {default}] : "
    else:
        label_display = f"  {label} : "

    while True:
        value = input(label_display).strip()
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
    print("ETAPE 2 - Parametres de capture video")
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
    print("ETAPE 3 - Parametres de capture audio")
    print("-" * 50)
    print("  Laissez vide pour utiliser le microphone par defaut du systeme.")
    print()

    print("  Microphone utilise : periherique par defaut du systeme")

    print()
    print("Recapitulatif des parametres :")
    print("-" * 50)
    print(f"  Serveur LiveKit : {server_url}")
    print(f"  Cle API         : {api_key}")
    print(f"  Room            : {room_name}")
    print(f"  Camera          : index {camera_index}")
    print(f"  Micro           : periherique par defaut")
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
        "camera_index": camera_index
    }


async def test_connectivity(params):
    """
    Teste la connexion au serveur LiveKit avant de lancer le streaming.
    Retourne True si la connexion est etablie, False sinon.
    """
    from livekit import rtc
    import jwt
    import time

    print()
    print("Test de connectivite en cours...")

    payload = {
        "iss": params["api_key"],
        "sub": "connectivity-test",
        "name": "Test de connexion",
        "nbf": int(time.time()),
        "exp": int(time.time()) + 60,
        "video": {
            "room": params["room_name"],
            "roomJoin": True,
            "canPublish": False,
            "canSubscribe": False
        }
    }

    try:
        token = jwt.encode(payload, params["api_secret"], algorithm="HS256")
    except Exception as e:
        print(f"\nErreur de generation du token : {e}")
        print("Verifiez que vos cles API sont correctes.")
        return False

    room = rtc.Room()
    try:
        await room.connect(params["server_url"], token, rtc.RoomOptions(auto_subscribe=False))
        await room.disconnect()
        print("Connexion au serveur LiveKit reussie.")
        return True
    except Exception as e:
        error_msg = str(e).lower()
        print("\nEchec de la connexion au serveur LiveKit.")

        if "unauthorized" in error_msg or "401" in error_msg:
            print("Cause probable : cles API incorrectes ou token invalide.")
            print("Verifiez vos cles API et le secret.")
        elif "name resolution" in error_msg or "getaddrinfo" in error_msg or "dns" in error_msg:
            print("Cause probable : impossible de resoudre l'adresse du serveur.")
            print(f"Verifiez que '{params['server_url']}' est accessible depuis ce reseau.")
        elif "connection refused" in error_msg or "refused" in error_msg:
            print("Cause probable : le serveur est hors ligne ou le port est bloque.")
            print("Verifiez que le serveur LiveKit est bien demarre.")
        elif "timeout" in error_msg or "timed out" in error_msg:
            print("Cause probable : le serveur ne repond pas (timeout).")
            print("Verifiez votre connexion internet et l'etat du serveur.")
        elif "ssl" in error_msg or "certificate" in error_msg:
            print("Cause probable : probleme de certificat SSL.")
            print("Verifiez que l'URL commence bien par 'wss://' pour une connexion securisee.")
        else:
            print(f"Detail technique : {e}")

        return False


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
        "sub": "local-simulator",
        "name": "Simulateur Robot (local)",
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
