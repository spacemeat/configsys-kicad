# configsys-kicad — build KiCad from source

A [configsys](https://github.com/spacemeat/configsys) **code plugin** that builds KiCad from
source — a specific release tag *or* master/nightly — and overrides the base `kicad` component
(distro package / Flathub) wherever it's loaded and trusted. Use it when you want a KiCad your
distro doesn't package: a newer release, a nightly, or a custom-flagged build. It's the exact
shape of [configsys-blender](https://github.com/spacemeat/configsys-blender): a thin
orchestration driver plus a build recipe you own.

> ⚠️ **Building KiCad is heavy.** It pulls a large dependency tree (wxWidgets, Boost,
> **OpenCASCADE**, ngspice, …) and compiles for a long time. If you just want *a* working KiCad,
> the base component's distro package or Flathub build is far quicker — reach for this only when
> you specifically need a from-source build. The per-distro dependency list in `build-kicad.sh`
> is the wavy part; package names drift across distros/versions, so treat it as a starting point.

## Files

| File | Role |
| --- | --- |
| `plugin.hu` | manifest — name, `requires-abi`, `code:` (the driver), `data:` (the override) |
| `kicad.hu` | the `kicad` override: one `via: kicad-build` binding |
| `kicad.py` | the `KicadBuild(Driver)` — orchestration + `features:` → CMake, `DRIVERS` export |
| `build-kicad.sh` | the recipe: per-distro deps, clone, cmake/make/install (**you own the knobs**) |

## The binding

```
kicad: { install: [ { via: kicad-build  ref: 9.0.0  dir: kicad-git  features: [ scripting, spice, 3d ] } ] }
```

| field | meaning |
| --- | --- |
| `ref` | git tag to build (`9.0.0`, `8.0.6`) **or** `master` for nightly. Empty = default branch. A tag is reproducible; master tracks HEAD. |
| `dir` | build-tree parent, **scope-honored**: bare-relative → `~/<dir>` (user) or `/opt/<dir>` (system). Source, build, and the install prefix all live under it. |
| `features` | **optional** subset of the tokens below. **Absent = a full build (all three).** Listing it *trims* to that subset. |

### Feature tokens

| token | enables | CMake flag | extra dep |
| --- | --- | --- | --- |
| `scripting` | Python console + action plugins | `-DKICAD_SCRIPTING_WXPYTHON=ON` | wxPython |
| `spice` | ngspice circuit simulator | `-DKICAD_SPICE=ON` | ngspice |
| `3d` | 3D viewer + STEP export | `-DKICAD_USE_OCC=ON` | OpenCASCADE |

Note: OpenCASCADE is effectively a hard dependency of a usable KiCad, so the recipe installs it
regardless; omitting `3d` mainly drops the explicit STEP/3D-export flag. An unknown feature token
is rejected (loudly) before the build starts.

## Try it

```console
$ configsys plugin add github:you/configsys-kicad --ref v0.1.0
$ configsys plugin trust configsys-kicad     # it ships code — approve the exact contents
$ configsys where kicad                       # -> via kicad-build, selected here
$ configsys install kicad                      # clones, installs deps, builds, installs to <dir>/install
```

`get_version` reports `built` once `<dir>/install/bin/kicad` exists. `uninstall` LEAVES the
source tree in place (auto-removing a checkout with your local work would be too destructive) —
remove `<dir>` by hand. `fix-scope` MOVES the tree between `~` and `/opt` rather than rebuilding.

## Knobs you own (`build-kicad.sh`)

- **Dependencies** — on **Ubuntu/Debian** and **Fedora** the recipe pulls KiCad's *complete*
  build-dep set from the distro's own kicad package (`apt build-dep` / `dnf builddep`), so it stays
  correct as KiCad's deps drift (wx 3.2 → zstd → protobuf → nng …) instead of a hand list you chase.
  **Arch and openSUSE** keep an explicit list — the thing most likely to need a tweak there.
- **`KICAD_PPA`** (Ubuntu/Pop) — Ubuntu LTS ships an old wxWidgets (22.04 = 3.0), but KiCad ≥ 7
  needs wx 3.2, absent from stock jammy. The recipe adds the **KiCad releases PPA**
  (`ppa:kicad/kicad-9.0-releases` by default, with `-s` so `build-dep` gets its deb-src), which
  backports wx 3.2 + a current kicad source. Override `KICAD_PPA` for another series
  (`kicad-8.0-releases`, or `kicad-dev-nightly` for master). Debian carries current kicad itself.
- **`JOBS`** (parallel compile), **`CC_OVERRIDE`/`CXX_OVERRIDE`** (a specific compiler).
- The install goes to a **prefix under the build dir** (user-writable, no sudo); only the
  dependency step sudos (via the package manager).

The `Driver` contract this codes against is documented on `configsys/driver.py` and versioned by
`configsys.plugins.ABI_VERSION`.
