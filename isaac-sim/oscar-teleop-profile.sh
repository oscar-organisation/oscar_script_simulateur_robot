#!/bin/bash
# Profil teleoperation OSCAR — libere le CPU du Jetson pour le chemin video.
#
# Mesure du 28/08/2026 sur ROSMASTER M3 (Jetson Nano B01) :
#
#                        avant      apres
#   cadence camera       4.5 fps    8.6 fps
#   age image (median)   42 ms      16 ms
#   age image (max)      2494 ms    45 ms
#   fps publie LiveKit   4.4        9.4
#   images abandonnees   continues  aucune
#   charge (4 coeurs)    13.7       5.4
#
# Cause : Nav2, SLAM, le detecteur d objets et le pont MQTT consommaient plus
# d un coeur entier. L encodeur H.264 logiciel, prive de CPU, abandonnait des
# images. Il n est pas trop lent — il etait affame.
#
# Reversible : `docker restart m3pro` relance la configuration d origine.
#
#   Usage :  ./oscar-teleop-profile.sh [--status]

set -u
CONTAINER="${OSCAR_CONTAINER:-m3pro}"

# Noeuds inutiles a la teleoperation manuelle. Le detecteur, la navigation
# autonome et le pont MQTT restent disponibles : ils se relancent au
# redemarrage du conteneur, ou manuellement pour les essais concernes.
SUPERFLUS=(
  "nav2_bt_navigator"      "nav2_planner"          "nav2_controller"
  "nav2_behaviors"         "nav2_smoother"         "nav2_waypoint_follower"
  "nav2_velocity_smoother" "nav2_lifecycle_manager" "nav2_costmap"
  "slam_toolbox"           "nav2_slam_roblaude"    "slam.launch"
  "object_detector"        "pickplace.launch"
  "mapping_supervisor"     "mission_executor"
  "mqtt_bridge"            "roblaude_mqtt"
)

# Doivent rester vivants : sans eux, plus de video ni de commande.
ESSENTIELS=("component_container" "micro_ros_agent" "oscar_robot_media" "command_agent")

in_container() { docker exec "$CONTAINER" bash -lc "$1" 2>/dev/null; }

etat() {
  echo "Charge (4 coeurs, cible <= 4) :"
  uptime | sed 's/.*load average/  load average/'
  echo
  echo "Processus les plus consommateurs :"
  ps -eo pcpu,comm --sort=-pcpu | head -7 | sed 's/^/  /'
  echo
  echo "Chaine OSCAR :"
  for e in "${ESSENTIELS[@]}"; do
    if in_container "pgrep -f '$e' >/dev/null"; then
      echo "  [ok]      $e"
    else
      echo "  [ABSENT]  $e"
    fi
  done
}

if [ "${1:-}" = "--status" ]; then
  etat
  exit 0
fi

echo "=== AVANT ==="
etat
echo
echo "=== Suspension des noeuds non necessaires a la teleoperation ==="

arretes=0
for n in "${SUPERFLUS[@]}"; do
  if in_container "pgrep -f '$n' >/dev/null"; then
    in_container "pkill -TERM -f '$n'"
    echo "  arrete : $n"
    arretes=$((arretes + 1))
  fi
done

if [ "$arretes" -eq 0 ]; then
  echo "  (rien a arreter, profil deja applique)"
else
  sleep 4
  # Second passage pour les noeuds qui ignorent SIGTERM.
  for n in "${SUPERFLUS[@]}"; do
    in_container "pkill -KILL -f '$n'" 2>/dev/null
  done
  sleep 3
fi

echo
echo "=== APRES ==="
etat

echo
manquants=0
for e in "${ESSENTIELS[@]}"; do
  in_container "pgrep -f '$e' >/dev/null" || manquants=$((manquants + 1))
done

if [ "$manquants" -gt 0 ]; then
  echo "ATTENTION : $manquants element(s) essentiel(s) absent(s) — voir la liste ci-dessus."
  echo "Relancer : docker restart $CONTAINER"
  exit 1
fi

echo "Profil teleoperation actif. La charge met environ une minute a redescendre."
echo "Pour restaurer navigation et perception : docker restart $CONTAINER"
