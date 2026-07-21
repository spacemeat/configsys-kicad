#!/usr/bin/env bash
# build-kicad.sh — configsys-kicad's build recipe, invoked by the kicad-build driver as
#   build-kicad.sh <ref> <root-dir>
# with KICAD_FEATURES ("scripting spice 3d" subset) and KICAD_CMAKE (the matching -D flags)
# in the environment. Core is transcribed from KiCad's "Building KiCad on Linux" docs.
#
# ---- YOU OWN THE KNOBS BELOW ----  (compiler, jobs, and the per-distro dependency lists,
# which drift with distro/KiCad versions — this is the wavy part; adjust names as needed.)
set -euo pipefail

REF="${1:-}"                                   # git tag/branch, e.g. 9.0.0 or master (empty = default)
ROOT="${2:?build root dir required}"           # parent dir, e.g. ~/kicad-git
FEATURES="${KICAD_FEATURES:-scripting spice 3d}"
CMAKE_FEATURES="${KICAD_CMAKE:-}"              # -D flags the driver derived from features:
SRC="$ROOT/kicad"
BUILD="$SRC/build"
PREFIX="$ROOT/install"

# --- knobs -----------------------------------------------------------------
JOBS="$(nproc 2>/dev/null || echo 4)"
CC_OVERRIDE=""            # e.g. "gcc-14" (empty = system default compiler)
CXX_OVERRIDE=""
# ---------------------------------------------------------------------------

has() { case " $FEATURES " in *" $1 "*) return 0;; *) return 1;; esac; }

# 0/1. dependencies (base + per-feature), per package manager. `git`/`cmake`/compiler included.
#      KiCad needs OCC (3D kernel) for a usable build, so it's in the base set regardless.
if command -v apt-get >/dev/null 2>&1; then
    # Ubuntu LTS ships an OLD wxWidgets (22.04 = 3.0) but KiCad >= 7 needs wx 3.2, so
    # libwxgtk3.2-dev isn't in stock jammy at all. The KiCad releases PPA backports wx 3.2 AND a
    # matching wxPython 4.2 as binaries — add it on Ubuntu/Pop so the deps below resolve. (Debian
    # itself carries wx 3.2, so it skips the PPA.) Verified on ubuntu:22.04. Set KICAD_PPA to the
    # series you build: kicad-9.0-releases / kicad-8.0-releases / kicad-dev-nightly.
    . /etc/os-release 2>/dev/null || true
    if [ "${ID:-}" = ubuntu ] || printf '%s' "${ID_LIKE:-}" | grep -qw ubuntu; then
        sudo apt-get update
        sudo apt-get install -y software-properties-common ca-certificates
        sudo add-apt-repository -y "${KICAD_PPA:-ppa:kicad/kicad-9.0-releases}"
    fi
    pkgs=(cmake g++ git swig python3-dev libwxgtk3.2-dev libboost-all-dev libglew-dev libglm-dev
          libcairo2-dev libbz2-dev libcurl4-openssl-dev libssl-dev libgit2-dev libgtk-3-dev
          gettext unixodbc-dev libsecret-1-dev
          libocct-foundation-dev libocct-data-exchange-dev libocct-visualization-dev
          libocct-modeling-algorithms-dev libocct-modeling-data-dev libocct-ocaf-dev)
    has scripting && pkgs+=(python3-wxgtk4.0)
    has spice     && pkgs+=(libngspice0-dev)
    sudo apt-get update && sudo apt-get install -y "${pkgs[@]}"
elif command -v dnf >/dev/null 2>&1; then
    pkgs=(cmake gcc-c++ git swig python3-devel wxGTK-devel boost-devel glew-devel glm-devel
          cairo-devel bzip2-devel libcurl-devel openssl-devel libgit2-devel gtk3-devel
          gettext-devel unixODBC-devel libsecret-devel opencascade-devel)
    has scripting && pkgs+=(python3-wxpython4)
    has spice     && pkgs+=(ngspice-devel)
    sudo dnf install -y "${pkgs[@]}"
elif command -v pacman >/dev/null 2>&1; then
    pkgs=(cmake gcc git swig python wxwidgets-gtk3 boost glew glm cairo curl openssl libgit2
          gtk3 gettext unixodbc libsecret opencascade)
    has scripting && pkgs+=(python-wxpython)
    has spice     && pkgs+=(ngspice)
    sudo pacman -S --needed --noconfirm "${pkgs[@]}"
elif command -v zypper >/dev/null 2>&1; then
    pkgs=(cmake gcc-c++ git swig python3-devel wxWidgets-3_2-devel boost-devel glew-devel
          glm-devel cairo-devel libcurl-devel libopenssl-devel libgit2-devel gtk3-devel
          gettext-tools unixODBC-devel libsecret-devel opencascade-devel)
    has scripting && pkgs+=(python3-wxPython)
    has spice     && pkgs+=(ngspice-devel)
    sudo zypper install -y "${pkgs[@]}"
else
    echo "build-kicad: unknown package manager — install KiCad's build deps yourself" >&2
    exit 1
fi

# 2. sources
mkdir -p "$ROOT"
if [ ! -d "$SRC/.git" ]; then
    git clone https://gitlab.com/kicad/code/kicad.git "$SRC"
fi
cd "$SRC"
git fetch --tags --quiet || true
[ -n "$REF" ] && git checkout "$REF"

# 3. configure (into a prefix under the build tree — a user-writable install, no sudo)
CC_ENV=()
[ -n "$CC_OVERRIDE" ]  && CC_ENV+=("CC=$CC_OVERRIDE")
[ -n "$CXX_OVERRIDE" ] && CC_ENV+=("CXX=$CXX_OVERRIDE")
# shellcheck disable=SC2086
env "${CC_ENV[@]}" cmake -B "$BUILD" -S "$SRC" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    $CMAKE_FEATURES

# 4. build + install
cmake --build "$BUILD" -j "$JOBS"
cmake --install "$BUILD"

echo "build-kicad: installed to $PREFIX"
echo "build-kicad: run it with  $PREFIX/bin/kicad   (features: $FEATURES)"
