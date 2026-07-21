'''Unit tests for the kicad-build driver — command construction + feature handling in pretend
mode (no actual build). Run from this dir with configsys importable:  python -m pytest -q
(a full KiCad build is far too heavy for CI, so the recipe itself is validated by hand; this
covers the driver logic the recipe depends on).'''

from pathlib import Path

import pytest

from configsys import plugins
from configsys.componentObj import ResolvedComponent
from configsys.runner import Runner

PLUG = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def KicadBuild():
    return plugins._import_drivers(PLUG, plugins.read_manifest(PLUG))[0]


def _rc(**fields):
    return ResolvedComponent(key='kicad-build\\kicad', driver='kicad-build', comp='kicad',
                             fields=dict(fields), source=str(PLUG / 'kicad.hu'))


def test_manifest_and_class(KicadBuild):
    m = plugins.read_manifest(PLUG)
    assert m['name'] == 'configsys-kicad' and m['code'] == 'kicad.py'
    assert KicadBuild.name == 'kicad-build'
    assert KicadBuild.default_scope == 'user' and KicadBuild.honors_scope and not KicadBuild.privileged


def test_features_default_is_full(KicadBuild):
    d = KicadBuild(Runner(pretend=True))
    assert d._features(_rc()) == ['scripting', 'spice', '3d']            # absent = all
    assert d._features(_rc(features=['3d'])) == ['3d']                   # listed = trimmed
    assert d._features(_rc(features='spice')) == ['spice']               # scalar accepted
    assert d._features(_rc(features=['3d', '3d'])) == ['3d']             # deduped


def test_unknown_feature_rejected(KicadBuild):
    d = KicadBuild(Runner(pretend=True))
    with pytest.raises(ValueError):
        d._features(_rc(features=['bogus']))
    # ...and install turns that into a clean failed Result, never runs the recipe
    r = Runner(pretend=True)
    res = KicadBuild(r).install(_rc(features=['bogus']))
    assert not res.ok
    assert not any('build-kicad.sh' in c for c in r.calls)


def test_feature_cmake_flags(KicadBuild):
    d = KicadBuild(Runner(pretend=True))
    assert d._feature_cmake(['spice']) == '-DKICAD_SPICE=ON'
    full = d._feature_cmake(['scripting', 'spice', '3d'])
    assert '-DKICAD_SCRIPTING_WXPYTHON=ON' in full and '-DKICAD_USE_OCC=ON' in full


def test_install_command(KicadBuild):
    r = Runner(pretend=True)
    KicadBuild(r).install(_rc(ref='9.0.0', dir='kicad-git', features=['3d']))
    call = r.calls[-1]
    assert 'KICAD_FEATURES=3d ' in call                          # single token, shlex leaves it bare
    assert 'KICAD_CMAKE=-DKICAD_USE_OCC=ON ' in call
    assert 'build-kicad.sh' in call
    assert call.rstrip().endswith('9.0.0 ' + str(Path.home() / 'kicad-git'))   # <ref> <build-dir>

    # a multi-token features string DOES get quoted
    r2 = Runner(pretend=True)
    KicadBuild(r2).install(_rc(ref='master', dir='kicad-git'))   # full build -> all three
    assert "KICAD_FEATURES='scripting spice 3d'" in r2.calls[-1]


def test_get_version_reports_the_built_tag(KicadBuild):
    from configsys.runner import Result

    class Fake:
        def __init__(self, built=True, describe='9.0.0'):
            self.built, self.describe, self.calls = built, describe, []

        def run(self, cmd, **kw):
            self.calls.append(cmd)
            if cmd.startswith('test -x'):
                return Result(cmd, 0 if self.built else 1)
            if 'describe' in cmd:
                return Result(cmd, 0, stdout=self.describe + '\n')
            return Result(cmd, 0)

    # built at the tag -> version IS the tag, so it matches get_latest (the ref) => "up to date"
    d = KicadBuild(Fake(describe='9.0.0'))
    assert d.get_version(_rc(dir='kicad-git', ref='9.0.0')) == '9.0.0'
    assert d.get_latest(_rc(ref='9.0.0')) == '9.0.0'
    assert any('describe --tags' in c for c in d.runner.calls)
    # not built -> None (no describe attempted)
    nb = KicadBuild(Fake(built=False))
    assert nb.get_version(_rc(dir='kicad-git')) is None
    assert not any('describe' in c for c in nb.runner.calls)
    # a master build describes as <tag>-<n>-g<hash>; falls back to 'built' if undescribable
    assert KicadBuild(Fake(describe='')).get_version(_rc(dir='kicad-git')) == 'built'


def test_reconcile_scope_moves_the_tree(KicadBuild):
    r = Runner(pretend=True)
    KicadBuild(r).reconcile_scope(_rc(dir='kicad-git'), 'system', 'user')
    call = r.calls[-1]
    assert call.startswith('sudo ') and 'mv /opt/kicad-git ' in call and 'chown -R "$USER"' in call


def test_uninstall_leaves_the_tree(KicadBuild):
    d = KicadBuild(Runner(pretend=True))
    res = d.uninstall(_rc(dir='kicad-git'))
    assert res.ok   # a no-op success — source left in place
