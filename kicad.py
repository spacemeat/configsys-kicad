'''kicad.py — the `kicad-build` driver for the configsys-kicad plugin.

Builds KiCad from source (git clone + CMake) so you can run a release tag or master/nightly that
your distro doesn't package. The driver does the safe, generic orchestration (locate + run the
recipe, translate the `features:` field into CMake flags, report state, move the tree on a scope
fix); the wavy recipe — the long per-distro build-dep list, cmake/make/install — lives in
`build-kicad.sh` right next to this file. Edit that to own the tweakable bits.

Component shape:
    kicad: { install: [ { via: kicad-build  ref: 9.0.0  dir: kicad-git
                          features: [ scripting, spice, 3d ] } ] }
  ref       git tag/branch to build (e.g. 9.0.0, 8.0.6, or 'master'; empty = default branch)
  dir       build-tree parent, scope-honored (bare-relative -> ~/<dir> user, /opt/<dir> system)
  features  OPTIONAL subset of { scripting, spice, 3d }. ABSENT = a FULL build (all three).
            Listing it restricts to that subset. Each token maps to KiCad CMake flags (below) and
            the recipe installs its per-distro deps. An unknown token is caught here, loudly,
            before the (long) build.

`get_version` reports 'built' once the recipe's install prefix has a `kicad` binary. Uninstall
LEAVES the source tree in place (auto-removing a checkout with your local work is too
destructive). The driver is user-space; the recipe's dependency step sudos itself.
'''

import shlex
from pathlib import Path

from configsys.plugins import Driver, Result

# KiCad optional features. token -> the CMake -D flags it turns on. Absent `features:` = ALL of
# these (a full build); listing `features:` restricts to that subset. The recipe installs the
# base build deps (compiler, wx, boost, ...) always and the per-feature deps for the selected
# tokens. Flags track KiCad 8/9; the recipe owns any version-specific tweaks. NOTE: OCC (the 3D
# kernel) is effectively a hard dependency of a usable KiCad, so leaving `3d` out mainly drops the
# STEP/3D-export CMake flag — the recipe still installs OCC. Keep this in lockstep with README.md.
_FEATURE_FLAGS = {
    'scripting': ['-DKICAD_SCRIPTING_WXPYTHON=ON'],   # Python console + action plugins (wxPython)
    'spice':     ['-DKICAD_SPICE=ON'],                # ngspice circuit simulator in the schematic editor
    '3d':        ['-DKICAD_USE_OCC=ON'],              # 3D viewer + STEP export (OpenCASCADE)
}
_ALL_FEATURES = list(_FEATURE_FLAGS)


class KicadBuild(Driver):
    name = 'kicad-build'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    def _build_dir(self, rc):
        return self.scoped_dir(rc.fields.get('dir') or 'kicad-git', rc)

    def _script(self, rc):
        # build-kicad.sh ships in THIS driver's plugin dir (next to kicad.py) — find it via
        # __file__, NOT next to rc.source. The binding may be overridden in another layer (a user's
        # config / primary plugin) that doesn't carry the recipe, so we can't assume it sits
        # beside the binding's source. (See the same fix in configsys-blender's blender.py.)
        return Path(__file__).resolve().parent / 'build-kicad.sh'

    def _binary(self, rc):
        # the recipe installs into <build-dir>/install (a scope-honored prefix)
        return self._build_dir(rc) / 'install' / 'bin' / 'kicad'

    # -- features ---------------------------------------------------------

    def _features(self, rc):
        '''The `features:` field as canonical tokens (deduped, order preserved). ABSENT = all
        (a full build). Raises ValueError on an unknown token.'''
        raw = rc.fields.get('features')
        if raw is None:
            return list(_ALL_FEATURES)
        if isinstance(raw, str):
            raw = [raw]
        out = []
        for tok in raw:
            if tok not in _FEATURE_FLAGS:
                raise ValueError(
                    f'unknown feature {tok!r} (want a subset of {", ".join(_ALL_FEATURES)})')
            if tok not in out:
                out.append(tok)
        return out

    def _feature_cmake(self, features):
        '''The deduped CMake flag string for a set of features.'''
        flags = []
        for f in features:
            for flag in _FEATURE_FLAGS[f]:
                if flag not in flags:
                    flags.append(flag)
        return ' '.join(flags)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        '''The version actually built = what the source tree is checked out at, via
        `git describe --tags`. For a tag build (`ref: 9.0.0`) that's exactly the tag, so it
        matches get_latest (the ref) and the menu reads "up to date" instead of "built" vs
        "9.0.0". A master/branch build describes as `<tag>-<n>-g<hash>` — legitimately ahead of
        the last release tag. Falls back to 'built' if the tree has no describable tag.'''
        if not self.runner.run(f'test -x {shlex.quote(str(self._binary(rc)))}').ok:
            return None
        src = self._build_dir(rc) / 'kicad'
        r = self.runner.run(f'git -C {shlex.quote(str(src))} describe --tags')
        return (r.stdout.strip() if r.ok else '') or 'built'

    def get_latest(self, rc):
        # the version you'd (re)build = the declared ref; matches get_version for a tag build.
        return rc.fields.get('ref') or 'built'

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        script = self._script(rc)
        if not script.exists():
            return Result(f'(kicad-build: recipe {script} not found)', 1)
        try:
            features = self._features(rc)
        except ValueError as e:
            return Result(f'(kicad-build: {e})', 1)
        cmake = self._feature_cmake(features)
        ref = shlex.quote(rc.fields.get('ref') or '')
        d = shlex.quote(str(self._build_dir(rc)))
        env = (f'KICAD_FEATURES={shlex.quote(" ".join(features))} '
               f'KICAD_CMAKE={shlex.quote(cmake)} ')
        return self.runner.run(
            f'{env}bash {shlex.quote(str(script))} {ref} {d}', capture=False)

    def upgrade(self, rc):
        return self.install(rc)   # fetch + checkout + rebuild

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc):
        return Result(f'(kicad-build: leaving {self._build_dir(rc)} in place; remove it by hand)', 0)

    def reconcile_scope(self, rc, detected, target):
        # MOVE the whole build tree between ~/kicad-git and /opt/kicad-git — never rebuild (a base
        # reinstall would recompile for a long time). Everything (source, build, install prefix)
        # lives under the one dir, so a move is complete. sudo when either side is /opt; chown back
        # to the user on ->user.
        had, saved = 'scope' in rc.fields, rc.fields.get('scope')
        try:
            rc.fields['scope'] = detected
            old = self._build_dir(rc)
            rc.fields['scope'] = target
            new = self._build_dir(rc)
        finally:
            if had:
                rc.fields['scope'] = saved
            else:
                rc.fields.pop('scope', None)
        if old == new:
            return Result('(kicad-build: already at the declared scope)', 0)
        tail = f' && chown -R "$USER" {shlex.quote(str(new))}' if (target == 'user' and detected == 'system') else ''
        return self.runner.run(
            f'mkdir -p {shlex.quote(str(new.parent))} && mv {shlex.quote(str(old))} '
            f'{shlex.quote(str(new))}{tail}',
            sudo='system' in (detected, target), capture=False)

    def lock(self, rc):
        return Result('(kicad-build lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(kicad-build unlock recorded in ledger)', 0)

    def location(self, rc):
        return str(self._build_dir(rc))


DRIVERS = [KicadBuild]
