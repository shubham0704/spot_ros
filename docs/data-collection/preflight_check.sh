#!/usr/bin/env bash
# Spot+Arm collection pre-flight check.
# Run ONCE at session start (and after any robot/launch change).
# Fails loudly when a critical condition is wrong so you don't collect bad data.
#
# Usage:   bash docs/data-collection/preflight_check.sh [BAG_ROOT]
# Default BAG_ROOT = ./bags
#
# Exit codes: 0 = PASS, 2 = WARN only, 1 = FAIL (critical)

set -uo pipefail
BAG_ROOT="${1:-./bags}"
HZ_TEST_SEC="${HZ_TEST_SEC:-4}"
HZ_WARN_MIN="${HZ_WARN_MIN:-1.0}"

# ----- pretty print helpers ---------------------------------------------------
R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[34m'; D=$'\e[0m'
fail_count=0; warn_count=0
pass(){ printf "${G}[PASS]${D} %s\n" "$*"; }
warn(){ printf "${Y}[WARN]${D} %s\n" "$*"; warn_count=$((warn_count+1)); }
fail(){ printf "${R}[FAIL]${D} %s\n" "$*"; fail_count=$((fail_count+1)); }
info(){ printf "${B}[info]${D} %s\n" "$*"; }
hdr (){ printf "\n=== %s ===\n" "$*"; }

# ----- 1. ROS env -------------------------------------------------------------
hdr "ROS 2 environment"
if ! command -v ros2 >/dev/null 2>&1; then
  fail "ros2 CLI not on PATH — source /opt/ros/<distro>/setup.bash and your workspace"
  exit 1
fi
pass "ros2 CLI: $(ros2 --version 2>/dev/null || echo present)"
[ -n "${ROS_DISTRO:-}" ] && pass "ROS_DISTRO=${ROS_DISTRO}" || warn "ROS_DISTRO unset"
[ -n "${ROS_DOMAIN_ID:-}" ] && info "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}" || warn "ROS_DOMAIN_ID unset (default 0)"

# ----- 2. Collection env vars -------------------------------------------------
hdr "Collection env (fps-debug / phase2)"
if [ "${SPOT_IMAGE_SERVER_FPS_DEBUG:-}" = "" ] || \
   [[ "${SPOT_IMAGE_SERVER_FPS_DEBUG}" =~ ^(0|false|False|no|off)$ ]]; then
  warn "SPOT_IMAGE_SERVER_FPS_DEBUG is OFF — per-episode camera-rate logs WILL BE MISSING"
  warn "  Recommended: export SPOT_IMAGE_SERVER_FPS_DEBUG=1 before launching the image server"
else
  pass "SPOT_IMAGE_SERVER_FPS_DEBUG=${SPOT_IMAGE_SERVER_FPS_DEBUG}"
fi
if [ "${SPOT_IMAGE_SERVER_RGB_JPEG:-}" = "" ] || \
   [[ "${SPOT_IMAGE_SERVER_RGB_JPEG}" =~ ^(0|false|False|no|off)$ ]]; then
  info "SPOT_IMAGE_SERVER_RGB_JPEG=off (RAW mode) — recording at the ~6 MB/s WiFi ceiling"
  IMG_MODE="raw"
else
  pass "SPOT_IMAGE_SERVER_RGB_JPEG=${SPOT_IMAGE_SERVER_RGB_JPEG} (Phase 2 compressed)"
  IMG_MODE="jpeg"
  info "SPOT_IMAGE_SERVER_JPEG_QUALITY=${SPOT_IMAGE_SERVER_JPEG_QUALITY:-75}"
fi

# ----- 3. spot_image_server node ---------------------------------------------
hdr "spot_image_server node"
NODES="$(ros2 node list 2>/dev/null || true)"
if echo "$NODES" | grep -q "spot_image_server"; then
  pass "spot_image_server node visible on the graph"
else
  fail "spot_image_server node NOT visible — launch spot_bringup with the image config"
fi

# ----- 4. spot_image_server services -----------------------------------------
hdr "spot_image_server services"
SERVICES="$(ros2 service list 2>/dev/null || true)"
for svc in /spot_image_server/list_registered_sources /spot_image_server/get_images; do
  if echo "$SERVICES" | grep -qx "$svc"; then
    pass "service available: $svc"
  else
    warn "service missing: $svc (analysis pulls won't work without get_images)"
  fi
done

# ----- 5. Camera topics — discover and check ---------------------------------
hdr "Camera topics (spot_image_server)"
TOPICS="$(ros2 topic list 2>/dev/null || true)"
if [ "$IMG_MODE" = "jpeg" ]; then
  PRIMARY_PATTERN="/spot_image_server/rgb/.*/image/compressed"
  ALT_PATTERN="/spot_image_server/depth/.*/image"
else
  PRIMARY_PATTERN="/spot_image_server/rgb/.*/image$"
  ALT_PATTERN="/spot_image_server/depth/.*/image$"
fi
RGB_TOPICS=$(echo "$TOPICS" | grep -E "$PRIMARY_PATTERN" || true)
DEPTH_TOPICS=$(echo "$TOPICS" | grep -E "$ALT_PATTERN" || true)
INFO_TOPICS=$(echo "$TOPICS" | grep -E "/spot_image_server/.*/camera_info$" || true)

if [ -z "$RGB_TOPICS" ]; then
  fail "No RGB topics matching $PRIMARY_PATTERN"
  fail "  IMG_MODE=$IMG_MODE — did you set SPOT_IMAGE_SERVER_RGB_JPEG correctly before launch?"
else
  N=$(echo "$RGB_TOPICS" | wc -l | tr -d ' ')
  pass "RGB image topics: $N"
  echo "$RGB_TOPICS" | sed 's/^/      /'
fi
if [ -z "$DEPTH_TOPICS" ]; then
  warn "No depth image topics found (depth/<src>/image)"
else
  N=$(echo "$DEPTH_TOPICS" | wc -l | tr -d ' ')
  pass "depth image topics: $N"
fi
if [ -z "$INFO_TOPICS" ]; then
  warn "No camera_info topics found — calibration won't be in the bag"
else
  N=$(echo "$INFO_TOPICS" | wc -l | tr -d ' ')
  pass "camera_info topics: $N"
fi

# ----- 6. Hz check on one representative camera ------------------------------
if [ -n "$RGB_TOPICS" ]; then
  T=$(echo "$RGB_TOPICS" | head -n1)
  hdr "Live rate check  ($T  for ${HZ_TEST_SEC}s)"
  HZ_OUT=$(timeout "$HZ_TEST_SEC" ros2 topic hz "$T" 2>&1 | tail -n 5 || true)
  # Parse "average rate: <num>"
  HZ=$(echo "$HZ_OUT" | grep -oE "average rate: [0-9.]+" | tail -n1 | awk '{print $3}')
  if [ -n "$HZ" ]; then
    awk -v h="$HZ" -v m="$HZ_WARN_MIN" 'BEGIN{exit !(h+0 >= m+0)}' \
      && pass "$T avg rate ${HZ} Hz  (>= ${HZ_WARN_MIN})" \
      || warn "$T avg rate ${HZ} Hz  (< ${HZ_WARN_MIN})  — possible bandwidth-bound / publisher idle"
  else
    warn "Could not parse a rate from 'ros2 topic hz' (no subscribers may mean no traffic; this is the gate-and-collapse behavior)"
  fi
fi

# ----- 7. Non-image topics — discover-and-report -----------------------------
hdr "Non-image topics (discover & verify on this robot)"
# Patterns verified against spot_driver/spot_driver/spot_ros.py source
# (node name "spot_driver" → /spot_driver/* prefix). Last value "optional"
# means a WARN is informational rather than a real problem.
declare -A NEEDED_PATTERNS=(
  ["tf"]="^/tf$"
  ["tf_static"]="^/tf_static$"
  ["joint_states"]="^/spot_driver/joint_states$"
  ["odometry"]="^/spot_driver/odometry$"
  ["battery_states"]="^/spot_driver/status/battery_states$"
  ["feet"]="^/spot_driver/status/feet$"
  ["power_state"]="^/spot_driver/status/power_state$"
  ["cmd_vel"]="^/spot_driver/cmd_vel$"
  ["wifi"]="^/spot_driver/status/wifi$"
)
for key in tf tf_static joint_states odometry battery_states feet power_state cmd_vel wifi; do
  pat="${NEEDED_PATTERNS[$key]}"
  match=$(echo "$TOPICS" | grep -E "$pat" || true)
  if [ -n "$match" ]; then
    pass "$key found: $match"
  else
    warn "$key NOT found by pattern '$pat' — confirm bringup launched spot_driver and the node name matches"
  fi
done

# IMU is intentionally listed as informational — spot_driver in this branch
# does NOT publish an /imu topic (verified in source). Stability comes from
# odometry twist + status/feet.
IMU_MATCH=$(echo "$TOPICS" | grep -Ei "(^|/)imu" || true)
if [ -n "$IMU_MATCH" ]; then
  info "IMU topic(s) present (external): $IMU_MATCH"
else
  info "No IMU topic — expected (spot_driver does not publish one in this branch). Use odom twist + status/feet for stability."
fi

# Lidar / point cloud (conditional on EAP2 payload or filter)
PC_MATCH=$(echo "$TOPICS" | grep -Ei "(point_?cloud|velodyne|cloud_out)" || true)
if [ -n "$PC_MATCH" ]; then
  info "Point-cloud topic(s) present: $PC_MATCH"
else
  info "No point-cloud topic detected (OK if lidar payload is not equipped/launched)."
fi

# SLAM / map (external; not from spot_driver)
SLAM_MATCH=$(echo "$TOPICS" | grep -Ei "(^/map$|/map_updates|slam|amcl)" || true)
if [ -n "$SLAM_MATCH" ]; then
  info "SLAM/map topic(s) present: $SLAM_MATCH"
else
  info "No SLAM/map topic detected (only relevant if you're running SLAM/Nav2)."
fi

info "Effort check (energy signal) — run: ros2 topic echo /spot_driver/joint_states --once"
info "  Confirm 'effort' field is populated (Spot often leaves it empty; if so, find a current/power topic and record metadata note)."

# ----- 8. rosbag2 + disk -----------------------------------------------------
hdr "rosbag2 + storage"
if command -v ros2 >/dev/null && ros2 bag --help >/dev/null 2>&1; then
  pass "ros2 bag CLI available"
else
  fail "ros2 bag not available"
fi
mkdir -p "$BAG_ROOT" 2>/dev/null
if [ -w "$BAG_ROOT" ]; then
  FREE=$(df -BG --output=avail "$BAG_ROOT" 2>/dev/null | tail -n1 | tr -d ' G')
  if [ -n "$FREE" ] && [ "$FREE" -ge 20 ]; then
    pass "bag root writable: $BAG_ROOT  (free: ${FREE}G)"
  else
    warn "bag root writable: $BAG_ROOT  (free: ${FREE:-?}G — < 20G; raw bags can be huge)"
  fi
else
  fail "bag root not writable: $BAG_ROOT"
fi

# ----- 9. Curated record command suggestion ----------------------------------
hdr "Suggested 'ros2 bag record' command for the next episode"
RECORD_TOPICS=""
RECORD_TOPICS+=" $RGB_TOPICS $DEPTH_TOPICS $INFO_TOPICS"
for key in tf tf_static joint_states odometry battery_states feet power_state cmd_vel wifi; do
  pat="${NEEDED_PATTERNS[$key]}"
  RECORD_TOPICS+=" $(echo "$TOPICS" | grep -E "$pat" | tr '\n' ' ')"
done
# Add the spot_driver status topics that aren't in NEEDED_PATTERNS but are
# useful to record (faults, mobility, feedback, dock, leases, estop):
for extra in "status/system_faults" "status/behavior_faults" "status/mobility_params" "status/feedback" "status/dock_state" "status/leases" "status/estop" "odometry/twist"; do
  RECORD_TOPICS+=" $(echo "$TOPICS" | grep -E "^/spot_driver/${extra}$" | tr '\n' ' ')"
done
# Conditional: any point-cloud / lidar topic that's actually live
RECORD_TOPICS+=" $(echo "$TOPICS" | grep -Ei "(point_?cloud|velodyne|cloud_out)" | tr '\n' ' ')"
# Compact / dedupe
RECORD_TOPICS=$(echo "$RECORD_TOPICS" | tr ' ' '\n' | sed '/^$/d' | sort -u | tr '\n' ' ')
cat <<EOF
# Replace <route>/<behavior>/<rep> below with the real names.
ros2 bag record \\
  -o "$BAG_ROOT/<route>/<behavior>/rep_<NN>" \\
  --storage mcap \\
  $RECORD_TOPICS
EOF
info "First bag of a session SHOULD instead be a 10s 'ros2 bag record -a' dry-run,"
info "then 'ros2 bag info' it to confirm every expected topic is present at sane rates."

# ----- 10. Verdict ------------------------------------------------------------
hdr "Verdict"
if [ "$fail_count" -gt 0 ]; then
  printf "${R}FAIL${D}: %d critical issue(s); %d warning(s). Do NOT start bulk collection.\n" "$fail_count" "$warn_count"
  exit 1
elif [ "$warn_count" -gt 0 ]; then
  printf "${Y}WARN${D}: %d warning(s); 0 critical. Address before bulk collection if possible.\n" "$warn_count"
  exit 2
else
  printf "${G}PASS${D}: cleared for collection.\n"
  exit 0
fi
