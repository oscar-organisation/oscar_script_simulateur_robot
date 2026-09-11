"""Diagnostic de latence OSCAR — à exécuter sur le robot, sans rien perturber.

Mesure le premier tiers de la chaîne (celui qui échappe aux statistiques
WebRTC du navigateur) et rapporte où part le temps avant l'encodage :

    caméra -> pilote ROS -> file d'attente -> notre agent

Sortie : âge des images, cadence réelle, gigue, charge par cœur, et liste des
nœuds ROS qui consomment le CPU en concurrence du chemin vidéo.

    docker exec m3pro bash -lc "source /opt/ros/humble/setup.bash && \
      source /root/yahboomcar_ws/install/setup.bash && \
      python3 /root/roblaude_ws/oscar/oscar_latency_probe.py --seconds 20"

Lecture seule : souscrit un topic, ne publie rien, ne modifie aucun nœud.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import time

import rclpy
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import Image


def _cpu_snapshot() -> str:
    """Charge moyenne + occupation par cœur, sans dépendance externe."""
    try:
        with open("/proc/loadavg") as fh:
            load = fh.read().split()[:3]
        return f"load 1/5/15 min : {load[0]} / {load[1]} / {load[2]}"
    except Exception:
        return "charge indisponible"


def _ros_nodes() -> list[str]:
    try:
        out = subprocess.run(
            ["ros2", "node", "list"], capture_output=True, text=True, timeout=8
        ).stdout
        return [n.strip() for n in out.splitlines() if n.strip()]
    except Exception:
        return []


def _top_processes(limit: int = 6) -> list[str]:
    try:
        out = subprocess.run(
            ["ps", "-eo", "pcpu,comm", "--sort=-pcpu"],
            capture_output=True, text=True, timeout=8,
        ).stdout.splitlines()[1 : limit + 1]
        return [l.strip() for l in out]
    except Exception:
        return []


def main() -> int:
    p = argparse.ArgumentParser(description="Sonde de latence caméra -> agent")
    p.add_argument("--topic", default="/camera/color/image_raw")
    p.add_argument("--seconds", type=float, default=20.0)
    args = p.parse_args()

    ages_ms: list[float] = []
    gaps_ms: list[float] = []
    sizes: set[tuple[int, int, str]] = set()
    last_arrival: float | None = None

    rclpy.init()
    node = rclpy.create_node("oscar_latency_probe")

    # Même QoS que l'agent média : on mesure ce que l'agent voit réellement.
    qos = QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        durability=QoSDurabilityPolicy.VOLATILE,
    )

    def on_image(msg: Image) -> None:
        nonlocal last_arrival
        now = time.time()
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        # Âge = temps écoulé entre la capture (horodatage du pilote) et la
        # réception par un abonné. Contient le pilote, le transport DDS et
        # l'attente en file.
        if stamp > 0:
            ages_ms.append((now - stamp) * 1000.0)
        if last_arrival is not None:
            gaps_ms.append((now - last_arrival) * 1000.0)
        last_arrival = now
        sizes.add((msg.width, msg.height, msg.encoding))

    node.create_subscription(Image, args.topic, on_image, qos)

    print(f"Sonde sur {args.topic} pendant {args.seconds:.0f} s ...\n")
    deadline = time.time() + args.seconds
    while rclpy.ok() and time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

    node.destroy_node()
    rclpy.shutdown()

    print("=" * 62)
    print("ACQUISITION")
    print("=" * 62)
    if not gaps_ms:
        print(f"  Aucune image reçue sur {args.topic}.")
        print("  Le pilote caméra tourne-t-il ? (orbbec_camera dabai_dcw2.launch.py)")
        return 1

    fps = 1000.0 / statistics.mean(gaps_ms)
    print(f"  Format             : {', '.join(f'{w}x{h} {e}' for w, h, e in sizes)}")
    print(f"  Cadence mesurée    : {fps:.1f} fps  ({len(gaps_ms) + 1} images)")
    print(f"  Intervalle moyen   : {statistics.mean(gaps_ms):.0f} ms")
    print(f"  Intervalle max     : {max(gaps_ms):.0f} ms   <- pic de gigue")
    if len(gaps_ms) > 1:
        print(f"  Gigue (ecart-type) : {statistics.pstdev(gaps_ms):.0f} ms")

    if ages_ms:
        ages_sorted = sorted(ages_ms)
        p05 = ages_sorted[max(0, int(len(ages_sorted) * 0.05) - 1)]
        p95 = ages_sorted[int(len(ages_sorted) * 0.95) - 1]
        # L horodatage du pilote et l horloge systeme derivent l un par rapport
        # a l autre (NTP actif). L age ABSOLU porte donc un decalage inconnu et
        # n est pas comparable d une mesure a l autre. L etalement, lui, annule
        # tout decalage constant : c est la grandeur a suivre.
        etalement = max(ages_ms) - min(ages_ms)
        print()
        print("  Retard de mise en file (etalement de l age) :")
        print(f"    etalement max-min : {etalement:.0f} ms   <- METRIQUE DE REFERENCE")
        print(f"    etalement p05-p95 : {p95 - p05:.0f} ms")
        print()
        print("    Cible teleoperation : etalement < 50 ms. Au-dela, des images")
        print("    stagnent en file — signe de CPU insuffisant sur le chemin video.")
        print()
        print("  Age absolu (indicatif seulement, contient un decalage d horloge) :")
        print(f"    median : {statistics.median(ages_ms):.0f} ms   max : {max(ages_ms):.0f} ms")

    print()
    print("=" * 62)
    print("CONCURRENCE CPU")
    print("=" * 62)
    print(f"  {_cpu_snapshot()}")
    print()
    print("  Processus les plus consommateurs :")
    for line in _top_processes():
        print(f"    {line}")

    nodes = _ros_nodes()
    if nodes:
        # Nœuds connus pour disputer le CPU au chemin video pendant la teleop.
        gourmands = [
            n for n in nodes
            if any(k in n.lower() for k in
                   ("slam", "nav", "detect", "yolo", "map", "amcl", "costmap", "planner"))
        ]
        print()
        print(f"  Noeuds ROS actifs : {len(nodes)}")
        if gourmands:
            print("  Concurrents du chemin video (a suspendre en teleop pure) :")
            for n in gourmands:
                print(f"    - {n}")
        else:
            print("  Aucun noeud SLAM / navigation / detection detecte.")

    print()
    print("=" * 62)
    print("SUITE")
    print("=" * 62)
    print("  Comparer ce releve avec les statistiques WebRTC du navigateur")
    print("  (jitterBufferDelay, framesDecoded, RTT) pour situer le temps")
    print("  restant entre encodage, transport et lecture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
