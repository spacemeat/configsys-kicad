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

# 0/1. dependencies. KiCad's build-dep set is large and drifts every release (wx 3.2, zstd,
#      protobuf, nng, OCC, ...). Where the package manager can compute it from the distro's own
#      kicad package we do exactly that — `apt build-dep` / `dnf builddep` — which is FAR more
#      robust than a hand-kept list (that kept missing pieces: wx 3.2, then zstd, then protobuf...).
#      The rolling distros (Arch, openSUSE) keep an explicit list. NOTE: `features:` gates the CMake
#      FLAGS (below); on the build-dep distros the whole dep set installs regardless (harmless).
#      Verified on ubuntu:22.04 (apt build-dep) and fedora:41 (dnf builddep).
if command -v apt-get >/dev/null 2>&1; then
    # Ubuntu LTS ships an old wxWidgets (22.04 = 3.0) but KiCad >= 7 needs 3.2, so add the KiCad
    # releases PPA WITH source (-s enables the deb-src that build-dep needs) — it backports wx 3.2
    # and provides a current kicad source. Debian carries current kicad itself but still needs
    # deb-src enabled for build-dep. Set KICAD_PPA to your series (kicad-9.0-releases /
    # kicad-8.0-releases / kicad-dev-nightly).
    . /etc/os-release 2>/dev/null || true
    sudo apt-get update
    sudo apt-get install -y software-properties-common ca-certificates git cmake
    if [ "${ID:-}" = ubuntu ] || printf '%s' "${ID_LIKE:-}" | grep -qw ubuntu; then
        sudo add-apt-repository -y -s "${KICAD_PPA:-ppa:kicad/kicad-9.0-releases}"
        sudo apt-get update
    fi
    sudo apt-get build-dep -y kicad
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y dnf-plugins-core git cmake
    sudo dnf builddep -y kicad
elif command -v pacman >/dev/null 2>&1; then
    pkgs=(cmake gcc git swig python wxwidgets-gtk3 boost glew glm cairo curl openssl libgit2
          gtk3 gettext unixodbc libsecret opencascade zstd protobuf nng)
    has scripting && pkgs+=(python-wxpython)
    has spice     && pkgs+=(ngspice)
    sudo pacman -S --needed --noconfirm "${pkgs[@]}"
elif command -v zypper >/dev/null 2>&1; then
    pkgs=(cmake gcc-c++ git swig python3-devel wxWidgets-3_2-devel boost-devel glew-devel
          glm-devel cairo-devel libcurl-devel libopenssl-devel libgit2-devel gtk3-devel
          gettext-tools unixODBC-devel libsecret-devel opencascade-devel libzstd-devel protobuf-devel)
    has scripting && pkgs+=(python3-wxPython)
    has spice     && pkgs+=(ngspice-devel)
    sudo zypper install -y "${pkgs[@]}"
else
    echo "build-kicad: unknown package manager — install KiCad's build deps yourself" >&2
    exit 1
fi

# 2. sources
# Create the build root. At user scope $ROOT is under ~ (writable directly). At system scope it's
# /opt/... — a normal user can't mkdir there, so fall back to sudo and hand ownership back, and the
# rest of the build (clone, compile, install-to-prefix) runs unprivileged in place. That's how an
# admin's `scope: system` build finishes with everything world-readable under /opt, no root compile.
if ! mkdir -p "$ROOT" 2>/dev/null; then
    sudo mkdir -p "$ROOT" && sudo chown "$(id -un):$(id -gn)" "$ROOT"
fi
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
