#!/usr/bin/env bash
# =============================================================================
# OpenRouteService (ORS) Local Setup Script
# Target: Ubuntu desktop, running ORS as a plain JAR file
# Usage:  bash setup-ors.sh [--install-dir /path/to/dir] [--osm-region germany]
#         bash setup-ors.sh --help
# =============================================================================

set -euo pipefail

# ─────────────────────────────────────────────
# Defaults (override via flags or env variables)
# ─────────────────────────────────────────────
INSTALL_DIR="${ORS_INSTALL_DIR:-$HOME/openrouteservice}"
OSM_REGION="${ORS_OSM_REGION:-germany}"          # Geofabrik region slug
ORS_VERSION="${ORS_VERSION:-latest}"             # "latest" or a specific tag e.g. "9.5.1"
JAVA_XMS="${ORS_JAVA_XMS:-2g}"                   # JVM initial heap
JAVA_XMX="${ORS_JAVA_XMX:-12g}"                  # JVM max heap (Germany + elevation needs ~12-16 GB)
ORS_PORT="${ORS_PORT:-8080}"
GEOFABRIK_BASE="https://download.geofabrik.de"

# ─────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { printf "%b\n" "${CYAN}[INFO]${RESET}  $*"; }
success() { printf "%b\n" "${GREEN}[OK]${RESET}    $*"; }
warn()    { printf "%b\n" "${YELLOW}[WARN]${RESET}  $*"; }
error()   { printf "%b\n" "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ─────────────────────────────────────────────
# Usage / help
# ─────────────────────────────────────────────
usage() {
  printf "%b\n" "${BOLD}OpenRouteService local setup script${RESET}"
  printf "\n"
  printf "%b\n" "${BOLD}Usage:${RESET}"
  printf "  bash %s [OPTIONS]\n" "$(basename "$0")"
  printf "\n"
  printf "%b\n" "${BOLD}Options:${RESET}"
  printf "  -d, --install-dir DIR    Installation directory  (default: ~/openrouteservice)\n"
  printf "  -r, --osm-region REGION  Geofabrik region slug   (default: germany)\n"
  printf "                           Examples: germany, europe/france, north-america/us/california\n"
  printf "  -v, --ors-version VER    ORS release tag          (default: latest)\n"
  printf "  --java-xms SIZE          JVM initial heap         (default: 2g)\n"
  printf "  --java-xmx SIZE          JVM max heap             (default: 12g)\n"
  printf "  -p, --port PORT          Port ORS listens on      (default: 8080)\n"
  printf "  --start                  Start ORS after setup\n"
  printf "  -h, --help               Show this help\n"
  printf "\n"
  printf "%b\n" "${BOLD}Environment variable overrides:${RESET}"
  printf "  ORS_INSTALL_DIR, ORS_OSM_REGION, ORS_VERSION,\n"
  printf "  ORS_JAVA_XMS, ORS_JAVA_XMX, ORS_PORT\n"
  printf "\n"
  printf "%b\n" "${BOLD}Examples:${RESET}"
  printf "  # Minimal - Germany, default install dir\n"
  printf "  bash %s\n" "$(basename "$0")"
  printf "\n"
  printf "  # Custom directory, only car routing, auto-start\n"
  printf "  bash %s --install-dir /opt/ors --start\n" "$(basename "$0")"
  printf "\n"
  printf "  # Austria with more heap\n"
  printf "  bash %s --osm-region europe/austria --java-xmx 6g\n" "$(basename "$0")"
}

# ─────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────
AUTO_START=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--install-dir)  INSTALL_DIR="$2"; shift 2 ;;
    -r|--osm-region)   OSM_REGION="$2";  shift 2 ;;
    -v|--ors-version)  ORS_VERSION="$2"; shift 2 ;;
    --java-xms)        JAVA_XMS="$2";    shift 2 ;;
    --java-xmx)        JAVA_XMX="$2";    shift 2 ;;
    -p|--port)         ORS_PORT="$2";    shift 2 ;;
    --start)           AUTO_START=true;  shift   ;;
    -h|--help)         usage; exit 0 ;;
    *) die "Unknown option: $1  (run with --help)" ;;
  esac
done

# ─────────────────────────────────────────────
# Derived paths
# ─────────────────────────────────────────────
OSM_FILE_NAME="${OSM_REGION##*/}-latest.osm.pbf"   # e.g. germany-latest.osm.pbf
OSM_URL="${GEOFABRIK_BASE}/${OSM_REGION}-latest.osm.pbf"

DIR_FILES="${INSTALL_DIR}/files"
DIR_GRAPHS="${INSTALL_DIR}/graphs"
DIR_ELEVATION="${INSTALL_DIR}/elevation_cache"
DIR_LOGS="${INSTALL_DIR}/logs"
DIR_CONFIG="${INSTALL_DIR}/config"
OSM_DEST="${DIR_FILES}/${OSM_FILE_NAME}"
CONFIG_FILE="${DIR_CONFIG}/ors-config.yml"
START_SCRIPT="${INSTALL_DIR}/start-ors.sh"

# ─────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────
printf "\n"
printf "%b\n" "${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
printf "%b\n" "${BOLD}║     OpenRouteService — JAR Setup for Ubuntu      ║${RESET}"
printf "%b\n" "${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
printf "\n"
info "Install directory : ${INSTALL_DIR}"
info "OSM region        : ${OSM_REGION}"
info "ORS version       : ${ORS_VERSION}"
info "JVM heap          : ${JAVA_XMS} (initial) / ${JAVA_XMX} (max)"
info "Server port       : ${ORS_PORT}"
printf "\n"

# ─────────────────────────────────────────────
# Step 1 — Check prerequisites
# ─────────────────────────────────────────────
info "Step 1/6 — Checking prerequisites…"

check_java() {
  if ! command -v java &>/dev/null; then
    warn "Java not found. Installing OpenJDK 21…"
    sudo apt-get update -qq
    sudo apt-get install -y openjdk-21-jre-headless
  fi
  JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d. -f1)
  if [[ "$JAVA_VERSION" -lt 17 ]]; then
    die "Java 17+ is required. Found version ${JAVA_VERSION}. Install OpenJDK 21 and retry."
  fi
  success "Java ${JAVA_VERSION} found: $(command -v java)"
}

check_tool() {
  if ! command -v "$1" &>/dev/null; then
    warn "$1 not found. Installing…"
    sudo apt-get install -y "$1"
  fi
  success "$1 is available"
}

check_java
check_tool curl
check_tool wget

# ─────────────────────────────────────────────
# Step 2 — Create directory structure
# ─────────────────────────────────────────────
info "Step 2/6 — Creating directory structure under ${INSTALL_DIR}…"

mkdir -p "${DIR_FILES}" "${DIR_GRAPHS}" "${DIR_ELEVATION}" "${DIR_LOGS}" "${DIR_CONFIG}"
success "Directories created"

# ─────────────────────────────────────────────
# Step 3 — Download the ORS JAR
# ─────────────────────────────────────────────
info "Step 3/6 — Downloading ORS JAR…"

JAR_DEST="${INSTALL_DIR}/ors.jar"

if [[ -f "${JAR_DEST}" ]]; then
  warn "ors.jar already exists at ${JAR_DEST} — skipping download."
  warn "Delete it and re-run to force a fresh download."
else
  if [[ "${ORS_VERSION}" == "latest" ]]; then
    info "Resolving latest ORS release tag from GitHub…"
    ORS_VERSION=$(curl -fsSL \
      "https://api.github.com/repos/GIScience/openrouteservice/releases/latest" \
      | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
    info "Latest version resolved: ${ORS_VERSION}"
  fi

  JAR_URL="https://github.com/GIScience/openrouteservice/releases/download/${ORS_VERSION}/ors.jar"
  info "Downloading: ${JAR_URL}"
  wget --progress=bar:force -O "${JAR_DEST}" "${JAR_URL}" || \
    die "Failed to download ORS JAR. Check version tag or your internet connection."
  success "ORS JAR saved to ${JAR_DEST}"
fi

# ─────────────────────────────────────────────
# Step 4 — Download OSM data
# ─────────────────────────────────────────────
info "Step 4/6 — Downloading OSM data for '${OSM_REGION}'…"

if [[ -f "${OSM_DEST}" ]]; then
  warn "OSM file already exists: ${OSM_DEST} — skipping download."
  warn "Delete it and re-run to refresh the OSM data."
else
  info "Source URL: ${OSM_URL}"
  info "This may take several minutes depending on your connection (Germany ~3 GB)…"
  wget --progress=bar:force -O "${OSM_DEST}" "${OSM_URL}" || \
    die "Failed to download OSM data. Check the region slug (--osm-region) and your connection."
  success "OSM data saved to ${OSM_DEST}"
fi

# ─────────────────────────────────────────────
# Step 5 — Generate ors-config.yml
# ─────────────────────────────────────────────
info "Step 5/6 — Writing ORS configuration to ${CONFIG_FILE}…"

cat > "${CONFIG_FILE}" <<YAML
# ─────────────────────────────────────────────────────────────
# OpenRouteService configuration
# Generated by setup-ors.sh  —  edit as needed
# Full reference: https://giscience.github.io/openrouteservice/run-instance/configuration/
# ─────────────────────────────────────────────────────────────

server:
  port: ${ORS_PORT}

ors:
  engine:
    graphs_root_path: ${DIR_GRAPHS}

    # ── Elevation ─────────────────────────────────────────────
    elevation:
      preprocessed: false          # ORS downloads SRTM tiles automatically
      data_access: MMAP
      cache_path: ${DIR_ELEVATION}
      cache_clear: false

    # profile_default applies to all profiles unless overridden per-profile
    profile_default:
      build:
        source_file: ${OSM_DEST}
        elevation: true            # Enable elevation on all profiles

    # ── Routing profiles ──────────────────────────────────────
    # Uncomment additional profiles as needed.
    # Each extra profile multiplies build time and RAM usage.
    # After changing profiles, delete the graphs dir and restart.
    profiles:
      driving-car:
        enabled: true
        build:
          source_file: ${OSM_DEST}

      # driving-hgv:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

      # cycling-regular:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

      # cycling-mountain:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

      # cycling-electric:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

      # foot-walking:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

      # foot-hiking:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

      # wheelchair:
      #   enabled: true
      #   build:
      #     source_file: ${OSM_DEST}

  # ── Logging ─────────────────────────────────────────────────
logging:
  file:
    name: ${DIR_LOGS}/ors.log
  level:
    root: WARN
    org.heigit: INFO
YAML

success "Config written to ${CONFIG_FILE}"

# ─────────────────────────────────────────────
# Step 6 — Write start script
# ─────────────────────────────────────────────
info "Step 6/6 — Writing start script to ${START_SCRIPT}…"

cat > "${START_SCRIPT}" <<BASH
#!/usr/bin/env bash
# ─────────────────────────────────────────────
# Start OpenRouteService (JAR mode)
# Edit JAVA_XMS / JAVA_XMX to tune heap size.
# Germany + elevation + 1 profile needs ~8-12 GB.
# ─────────────────────────────────────────────

INSTALL_DIR="${INSTALL_DIR}"
JAR="\${INSTALL_DIR}/ors.jar"
CONFIG="\${INSTALL_DIR}/config/ors-config.yml"
LOG="\${INSTALL_DIR}/logs/ors.log"

JAVA_XMS="${JAVA_XMS}"
JAVA_XMX="${JAVA_XMX}"

echo "Starting OpenRouteService on port ${ORS_PORT}…"
echo "Config:       \${CONFIG}"
echo "Logs:         \${LOG}"
echo "Health check: http://localhost:${ORS_PORT}/ors/v2/health"
echo ""
echo "NOTE: First startup builds the routing graph from the OSM data."
echo "      For Germany this can take 1-3 hours per active profile."
echo ""

# ORS looks for ors-config.yml relative to the working directory by default.
# We cd to the install dir so that relative paths in the config resolve correctly,
# and we also set ORS_CONFIG_LOCATION explicitly to guarantee the right file is loaded
# regardless of where this script is called from.
cd "\${INSTALL_DIR}"

export ORS_CONFIG_LOCATION="\${CONFIG}"

exec java \\
  -Djava.awt.headless=true \\
  -server \\
  -Xms\${JAVA_XMS} \\
  -Xmx\${JAVA_XMX} \\
  -XX:+UseG1GC \\
  -XX:+ScavengeBeforeFullGC \\
  -XX:TargetSurvivorRatio=75 \\
  -XX:SurvivorRatio=64 \\
  -XX:MaxTenuringThreshold=3 \\
  -XX:ParallelGCThreads=4 \\
  -Dcom.sun.management.jmxremote \\
  -Dcom.sun.management.jmxremote.port=9001 \\
  -Dcom.sun.management.jmxremote.rmi.port=9001 \\
  -Dcom.sun.management.jmxremote.authenticate=false \\
  -Dcom.sun.management.jmxremote.ssl=false \\
  -Djava.rmi.server.hostname=localhost \\
  -jar "\${JAR}" \\
  2>&1 | tee -a "\${LOG}"
BASH

chmod +x "${START_SCRIPT}"
success "Start script written: ${START_SCRIPT}"

# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
printf "\n"
printf "%b\n" "${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
printf "%b\n" "${BOLD}║                 Setup complete!                  ║${RESET}"
printf "%b\n" "${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
printf "\n"
printf "  %b%s%b   %s\n" "${BOLD}" "Install dir:"     "${RESET}" "${INSTALL_DIR}"
printf "  %b%s%b      %s\n" "${BOLD}" "OSM data:"      "${RESET}" "${OSM_DEST}"
printf "  %b%s%b        %s\n" "${BOLD}" "Config:"       "${RESET}" "${CONFIG_FILE}"
printf "  %b%s%b  %s\n" "${BOLD}" "Graphs cache:"     "${RESET}" "${DIR_GRAPHS}"
printf "  %b%s%b %s\n" "${BOLD}" "Elevation cache:"   "${RESET}" "${DIR_ELEVATION}"
printf "  %b%s%b          %s\n" "${BOLD}" "Logs:"       "${RESET}" "${DIR_LOGS}/ors.log"
printf "\n"
printf "  %b%s%b\n" "${BOLD}" "To start ORS:" "${RESET}"
printf "    %b%s%b\n" "${CYAN}" "bash ${START_SCRIPT}" "${RESET}"
printf "\n"
printf "  %b%s%b\n" "${BOLD}" "Check health:" "${RESET}"
printf "    %b%s%b\n" "${CYAN}" "curl http://localhost:${ORS_PORT}/ors/v2/health" "${RESET}"
printf "\n"
printf "  %b%s%b\n" "${BOLD}" "Enable more profiles:" "${RESET}"
printf "    Edit %s and uncomment the profiles you need,\n" "${CONFIG_FILE}"
printf "    then delete %s and restart to rebuild.\n" "${DIR_GRAPHS}"
printf "\n"
warn "First startup will build the routing graph from OSM data."
warn "For Germany (1 profile + elevation) this typically takes 1-3 hours."
warn "RAM recommendation: 12-16 GB available for Germany + elevation."
printf "\n"

# ─────────────────────────────────────────────
# Auto-start if requested
# ─────────────────────────────────────────────
if [[ "${AUTO_START}" == true ]]; then
  info "Auto-starting ORS (--start flag was set)…"
  bash "${START_SCRIPT}"
fi