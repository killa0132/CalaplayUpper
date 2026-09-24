# -*- coding: utf-8 -*-
"""CalaPlayerSrcmBuilder -- one-stop srcm -> static _P patch pipeline.

Stages
------
L0  read-only preflight   : discover game + srcm, stage native containers,
                            extract the native shells / DA tables, validate the kit
L1  material normalisation: images -> 1920x1080 (cover|contain) -> BC1 mip chain
                            audio  -> PCM s16le / 48 kHz / <=2ch (ffmpeg only when needed)
L2  asset construction    : cooked Texture2D / USoundWave packages
L3  DataAsset append      : APPEND-ONLY rows into DA_Backgrounds / DA_BGM /
                            DA_Ambient / DA_Sounds
L4  pack + offline gates  : retoc to-zen + A0..A6
L5  deploy + final check  : back up the installed _P, copy ours in, read it back
                            from the REAL game folder, auto-rollback on failure

Safety contract
---------------
* L1..L4 only ever write inside <srcm-parent>/out_patch/
* L5 is the only stage that writes to the game folder, and only after backing up
* the native containers are never written (their hashes are recorded and re-checked)
* -DryRun stops after L4 and never touches the game folder
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import bc1, config, texture
from .common import (BuildError, Log, ProcResult, ensure_dir, hardlink_or_copy,
                     human, reconfigure_stdio, rmtree, run, run_ok, sha16,
                     sha256_bytes, sha256_file)
from .da import (AudioRow, BgRow, append_audio_rows, append_bg_rows,
                 assert_append_only, native_audio_count, parse_imports)
from .kit import FFMPEG_HELP, Kit, load_kit
from .wavutil import compliance, read_wav, verify_identity

TOOL_VERSION = "1.0.0"


# --------------------------------------------------------------------------
@dataclass
class Material:
    kind: str
    src: str
    rel: str
    name: str                    # ASCII object/package token
    key: str                     # dropdown display name (DA map key)
    pkg: str
    obj: str
    size_bytes: int = 0
    sha256: str = ""
    legacy_rel: str = ""         # e.g. CalaPlayer/Content/CalaPlayer/BGM/Name.uasset
    source_sha256: str = ""
    quality: Dict = field(default_factory=dict)
    audio: Dict = field(default_factory=dict)
    carried: bool = False
    upgraded: bool = False
    payload_bytes: int = 0
    note: str = ""


@dataclass
class Ctx:
    paks_arg: str
    srcm_arg: str
    fit: str = "cover"
    force: bool = False
    dry_run: bool = False
    combined: bool = False
    ffmpeg: Optional[str] = None
    kit_dir: Optional[str] = None
    keep_work: bool = False
    deploy: bool = True

    # discovered
    game: config.GamePaths = None
    srcm: Dict[str, str] = field(default_factory=dict)
    out_patch: str = ""
    work: str = ""
    prev_work: str = ""
    top_folder: str = ""
    names_json: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
class Builder:
    def __init__(self, ctx: Ctx, log: Log):
        self.c = ctx
        self.log = log
        self.kit: Optional[Kit] = None
        self.materials: List[Material] = []
        self.carried_materials: List[Material] = []
        self.gates: Dict[str, Dict] = {}
        self.da_base: Dict[str, str] = {}
        self.da_native_counts: Dict[str, int] = {}
        self.stages: List[Dict] = []
        self.container: Dict = {}
        self.deployed = False
        self.rollback: Dict = {}
        self._t0 = time.time()
        self._prev_manifest: Dict = {}

    # ------------------------------------------------------------------ util
    def _stage(self, name: str, fn):
        t0 = time.time()
        self.log(name, "---- stage %s: start ----" % name)
        try:
            fn()
        except BuildError:
            self.stages.append({"stage": name, "ok": False, "seconds": round(time.time() - t0, 2)})
            raise
        except Exception as e:  # noqa: BLE001 - convert to a stage-tagged error
            self.stages.append({"stage": name, "ok": False, "seconds": round(time.time() - t0, 2)})
            raise BuildError(name, "%s: %s" % (type(e).__name__, e))
        self.stages.append({"stage": name, "ok": True, "seconds": round(time.time() - t0, 2)})
        self.log(name, "---- stage %s: done (%.1fs) ----" % (name, time.time() - t0))

    def gate(self, gid: str, ok: bool, detail: str, fatal: bool = True) -> None:
        self.gates[gid] = {"ok": bool(ok), "detail": detail}
        self.log("GATE", "%s %s  %s" % (gid, "PASS" if ok else "FAIL", detail))
        if not ok and fatal:
            raise BuildError("L4", "gate %s failed" % gid, detail)

    # ================================================================= L0
    def l0(self) -> None:
        c, log = self.c, self.log
        c.game = config.discover_game(c.paks_arg)
        log("L0", "game paks dir : %s" % c.game.paks_dir)
        log("L0", "container base: %s" % c.game.container_base)
        log("L0", "native utoc(s): %s" % ", ".join(os.path.basename(x) for x in c.game.native_containers))
        if c.game.has_existing_patch:
            log("L0", "existing patch container in the game folder:")
            for ext, p in sorted(c.game.patch_files.items()):
                log("L0", "    %s  %s  %s" % (os.path.basename(p), human(os.path.getsize(p)), sha16(p)))
            locked = self._locked_patch_files()
            if locked:
                msg = ("the installed patch container is locked (%s) -- the game is most "
                       "likely still running. 请先关闭游戏再安装 / close the game first."
                       % ", ".join(locked))
                c.warnings.append(msg)
                log("L0", "WARN: " + msg)
        else:
            log("L0", "no patch container installed (clean game folder)")

        self.kit = load_kit(c.kit_dir, c.ffmpeg, log, "L0")
        if c.ffmpeg is None:
            c.ffmpeg = self.kit.ffmpeg

        c.srcm = config.discover_srcm(c.srcm_arg)
        log("L0", "srcm folders  : %s" % (", ".join("%s=%s" % (k, os.path.basename(v))
                                                    for k, v in c.srcm.items()) or "<none>"))
        missing = [k for k in config.KINDS if k not in c.srcm]
        if missing:
            log("L0", "NOTE: no material folder for: %s (skipped)" % ", ".join(missing))
        if not c.srcm:
            raise BuildError("L0", "srcm contains none of the 4 expected folders",
                             "expected %s" % ", ".join("bg/ BGM/ Sound/ Ambient/".split()))
        self._load_names_json()

        c.out_patch = ensure_dir(config.out_patch_dir(c.srcm_arg))
        c.work = os.path.join(c.out_patch, "work")
        # keep the previous build around so -Combined can accumulate
        prev = os.path.join(c.out_patch, "_prev_work")
        rmtree(prev)
        if os.path.isdir(c.work):
            os.rename(c.work, prev)
            c.prev_work = prev
        ensure_dir(c.work)
        log("L0", "out_patch     : %s" % c.out_patch)
        log("L0", "work dir      : %s" % c.work)

        if c.prev_work and os.path.isfile(os.path.join(c.prev_work, "manifest.json")):
            try:
                self._prev_manifest = json.load(
                    open(os.path.join(c.prev_work, "manifest.json"), encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                log("L0", "WARN: cannot read the previous manifest (%s)" % e)
        elif c.combined:
            msg = ("-Combined was given but there is no previous build in this out_patch, so "
                   "there is nothing to carry: the container will contain this run's srcm only."
                   " (The container currently installed in the game folder is still MOVED to "
                   "out_patch\\_prev_container as the rollback source.)")
            c.warnings.append(msg)
            log("L0", "WARN: " + msg)
        prev_names = [m["name"] for m in self._prev_manifest.get("materials", [])]
        if c.game.has_existing_patch and not c.combined:
            warn = ("the game folder already has a patch container installed. Its content is "
                    "NOT carried into the new container (it is only MOVED to "
                    "out_patch\\_prev_container as the rollback source). Put those materials "
                    "into srcm as well, or re-run with -Combined against the same out_patch.")
            c.warnings.append(warn)
            log("L0", "WARN: " + warn)
        if prev_names and not c.combined:
            log("L0", "WARN: the previous build in this out_patch already contains %d "
                      "material(s): %s" % (len(prev_names), ", ".join(prev_names[:12])))
            log("L0", "WARN: without -Combined they will NOT be part of this container "
                      "(the installed _P gets replaced). Add -Combined to accumulate.")

        self._scan_materials()
        self._check_limits()

        # stage the native containers (hardlinks: never write the game folder)
        self.native_paks = ensure_dir(os.path.join(c.work, "native_paks"))
        n = 0
        for f in sorted(os.listdir(c.game.paks_dir)):
            if config.looks_like_patch(f, c.game.container_base):
                continue
            src = os.path.join(c.game.paks_dir, f)
            if not os.path.isfile(src):
                continue
            hardlink_or_copy(src, os.path.join(self.native_paks, f), log, "L0")
            n += 1
        log("L0", "staged %d native container file(s) into work/native_paks" % n)

        # extract the shells + DA tables from the NATIVE containers only
        self._extract_native_bases()

        # record native hashes (proof we never touch them)
        self.native_hashes = {}
        for f in sorted(os.listdir(self.native_paks)):
            p = os.path.join(self.native_paks, f)
            self.native_hashes[f] = {"bytes": os.path.getsize(p), "sha256": sha256_file(p)}
            log("L0", "  native %-28s %12s  %s" % (f, human(os.path.getsize(p)), sha16(p)))

        log("L0", "materials found: %d" % len(self.materials))
        for m in self.materials:
            log("L0", "  [%s] %-34s -> name='%s' key='%s' pkg=%s"
                % (m.kind, m.rel, m.name, m.key, m.pkg))

    def _load_names_json(self) -> None:
        p = os.path.join(os.path.abspath(self.c.srcm_arg), config.NAME_JSON)
        if not os.path.isfile(p):
            return
        try:
            raw = json.load(open(p, encoding="utf-8-sig"))
        except Exception as e:  # noqa: BLE001
            raise BuildError("L0", "cannot parse %s" % p, str(e))
        if not isinstance(raw, dict):
            raise BuildError("L0", "%s must be a JSON object" % p)
        for k, v in raw.items():
            if isinstance(v, str):
                self.c.names_json[k.replace("\\", "/").strip().lower()] = v
        self.log("L0", "names.json    : %d custom display name(s)" % len(self.c.names_json))

    # ------------------------------------------------------------------ scan
    def _scan_materials(self) -> None:
        c, log = self.c, self.log
        used_names: set = set()
        used_keys: set = set()
        per_kind_nn: Dict[str, int] = {k: 0 for k in config.KINDS}
        for kind in config.KINDS:
            folder = c.srcm.get(kind)
            if not folder:
                continue
            exts = config.IMAGE_EXTS if kind == config.KIND_BG else config.AUDIO_EXTS
            files = sorted(f for f in os.listdir(folder)
                           if os.path.isfile(os.path.join(folder, f))
                           and f.lower().endswith(exts) and not f.startswith("."))
            others = sorted(f for f in os.listdir(folder)
                            if os.path.isfile(os.path.join(folder, f)) and f.startswith("."))
            for f in sorted(os.listdir(folder)):
                fp = os.path.join(folder, f)
                if os.path.isdir(fp):
                    log("L0", "  skip (subfolder is not scanned): %s/%s" % (kind, f))
                elif os.path.isfile(fp) and not f.lower().endswith(exts):
                    log("L0", "  skip (unsupported extension): %s/%s" % (kind, f))
            for f in files:
                stem = os.path.splitext(f)[0]
                fallback = "User_%s_%02d" % (
                    {"bg": "BG", "BGM": "BGM", "Sound": "Sound", "Ambient": "Ambient"}[kind],
                    per_kind_nn[kind] + 1)
                name = config.safe_token(stem, fallback)
                if not config.safe_token(stem, ""):
                    name = fallback
                per_kind_nn[kind] += 1
                # unique object name
                base = name
                i = 2
                while name.lower() in used_names:
                    name = "%s_%02d" % (base, i)
                    i += 1
                used_names.add(name.lower())
                # display key
                rel = "%s/%s" % (os.path.basename(folder), f)
                custom = c.names_json.get(rel.lower()) or c.names_json.get(
                    "%s/%s" % (kind.lower(), f.lower()))
                key = config.display_name(custom) if custom else config.display_name(stem)
                if not key:
                    key = name
                kbase, key_i = key, 2
                while key.lower() in used_keys:
                    key = "%s (%d)" % (kbase, key_i)
                    key_i += 1
                used_keys.add(key.lower())
                pkg = "%s/%s" % (config.KIND_PKG_FOLDER[kind], name)
                self.materials.append(Material(
                    kind=kind, src=os.path.abspath(os.path.join(folder, f)), rel=rel,
                    name=name, key=key, pkg=pkg, obj=name,
                    source_sha256=sha256_file(os.path.join(folder, f))))

    def _check_limits(self) -> None:
        c, log = self.c, self.log
        bgs = [m for m in self.materials if m.kind == config.KIND_BG]
        cap = config.limit_max_bg()
        ok = True
        if len(bgs) > cap:
            log("L0", "LIMIT: %d background(s) > %d" % (len(bgs), cap))
            ok = False
        if not ok and not c.force:
            raise BuildError("L0", "material count over the limit",
                             "background limit = %d; re-run with -Force to override" % cap)

    # ------------------------------------------------------- native extraction
    def _extract_native_bases(self) -> None:
        c, log, kit = self.c, self.log, self.kit
        nat = os.path.join(c.work, "native_raw")
        ensure_dir(nat)

        wanted = [
            ("shell_tex", config.TEX_SHELL, config.TEX_SHELL + ".uasset"),
            ("shell_snd", config.SND_SHELL, config.SND_SHELL + ".uasset"),
            ("DA_Backgrounds", config.DA_BACKGROUNDS, config.DA_BACKGROUNDS + ".uasset"),
            ("DA_BGM", config.DA_BGM, config.DA_BGM + ".uasset"),
            ("DA_Ambient", config.DA_AMBIENT, config.DA_AMBIENT + ".uasset"),
            ("DA_Sounds", config.DA_SOUNDS, config.DA_SOUNDS + ".uasset"),
        ]
        base = ensure_dir(os.path.join(c.work, "base"))
        for tag, pkg, _want in wanted:
            od = os.path.join(nat, tag)
            kit.to_legacy(self.native_paks, od, pkg.rsplit("/", 1)[-1], log, "L0")
            suffix = config.legacy_suffix_from_pkg(pkg) + ".uasset"
            found = None
            for root, _dirs, files in os.walk(od):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, od).replace("\\", "/")
                    parts = rel.split("/")
                    # legacy tree = <UE project folder>/Content/<path below /Game/>
                    if (len(parts) >= 3 and parts[1].lower() == "content"
                            and "/".join(parts[2:]) == suffix):
                        found = full
                        break
                if found:
                    break
            if not found:
                raise BuildError("L0", "native asset not extracted: %s" % suffix,
                                 "retoc to-legacy looked in %s" % od)
            if not c.top_folder:
                c.top_folder = os.path.relpath(found, od).replace("\\", "/").split("/")[0]
                config.TOP_FOLDER = c.top_folder
                log("L0", "legacy project folder = %s" % c.top_folder)
            dest_dir = ensure_dir(os.path.join(base, os.path.dirname(
                config.legacy_rel_from_pkg(pkg) + ".uasset")))
            for ext in (".uasset", ".uexp"):
                s = os.path.splitext(found)[0] + ext
                if os.path.isfile(s):
                    shutil.copy2(s, os.path.join(dest_dir, os.path.basename(s)))
            log("L0", "  base/%s  %s" % (os.path.dirname(
                config.legacy_rel_from_pkg(pkg) + ".uasset"), human(os.path.getsize(found))))

        if not c.top_folder:
            raise BuildError("L0", "could not determine the legacy project folder name")

        # validate the shells
        tex_ua = os.path.join(base, config.legacy_rel_from_pkg(config.TEX_SHELL) + ".uasset")
        tex_ux = os.path.join(base, config.legacy_rel_from_pkg(config.TEX_SHELL) + ".uexp")
        snd_ua = os.path.join(base, config.legacy_rel_from_pkg(config.SND_SHELL) + ".uasset")
        snd_ux = os.path.join(base, config.legacy_rel_from_pkg(config.SND_SHELL) + ".uexp")
        if not os.path.isfile(tex_ux):
            raise BuildError("L0", "texture shell uexp missing", tex_ux)
        if os.path.getsize(tex_ux) != config.TEX_SHELL_EXPECTED_UEXP:
            raise BuildError("L0", "texture shell uexp is %d B, expected %d"
                             % (os.path.getsize(tex_ux), config.TEX_SHELL_EXPECTED_UEXP),
                             "the game build does not match the shell this tool was calibrated on")
        if not os.path.isfile(snd_ux) or os.path.getsize(snd_ux) != config.SND_SHELL_EXPECTED_UEXP:
            raise BuildError("L0", "sound shell uexp size mismatch", snd_ux)
        log("L0", "shells OK: texture uexp=%d B, sound uexp=%d B"
            % (os.path.getsize(tex_ux), os.path.getsize(snd_ux)))
        self.tex_shell_ua, self.tex_shell_ux = tex_ua, tex_ux
        self.snd_shell_ua, self.snd_shell_ux = snd_ua, snd_ux

        # dump the texture shell mip layout once (offline, from the native staging dir)
        self.tex_dump = self.kit.tex_dump(self.native_paks, config.TEX_SHELL,
                                          os.path.join(c.work, "texdump"), log, "L0")
        self.tex_mips = texture.parse_mips(self.tex_dump)
        eq = [(m.size, (m.size == bc1.bc1_size(*self._mip_wh(i))))
              for i, m in enumerate(self.tex_mips)]
        log("L0", "texture shell mips = %d, sizes = %s"
            % (len(self.tex_mips), [m.size for m in self.tex_mips]))
        if len(self.tex_mips) != config.TEX_SHELL_MIPS:
            raise BuildError("L0", "texture shell has %d mips, expected %d"
                             % (len(self.tex_mips), config.TEX_SHELL_MIPS))
        texture.locate_mips(tex_ux, self.tex_mips)
        log("L0", "texture shell mip offsets verified (header=%d B, +%d B between mips)"
            % (self.tex_mips[0].offset, texture.INTER_MIP))

        for tag, pkg in (("DA_Backgrounds", config.DA_BACKGROUNDS),
                         ("DA_BGM", config.DA_BGM),
                         ("DA_Ambient", config.DA_AMBIENT),
                         ("DA_Sounds", config.DA_SOUNDS)):
            ua = os.path.join(base, config.legacy_rel_from_pkg(pkg) + ".uasset")
            ux = os.path.join(base, config.legacy_rel_from_pkg(pkg) + ".uexp")
            if not os.path.isfile(ux):
                raise BuildError("L0", "native DA not extracted: %s" % pkg, ux)
            self.da_base[tag] = ua
            if tag == "DA_Backgrounds":
                self.da_native_counts[tag] = struct.unpack_from(
                    "<I", open(ux, "rb").read(), 8)[0]
            else:
                self.da_native_counts[tag] = native_audio_count(ux)
            log("L0", "  %-16s native rows = %d (uexp %d B)"
                % (tag, self.da_native_counts[tag], os.path.getsize(ux)))

    def _mip_wh(self, i: int) -> Tuple[int, int]:
        w, h = config.TARGET_W, config.TARGET_H
        for _ in range(i):
            w, h = max(1, w // 2), max(1, h // 2)
        return w, h

    # ================================================================= L1
    def l1(self) -> None:
        c, log, kit = self.c, self.log, self.kit
        norm = ensure_dir(os.path.join(c.work, "norm"))

        # ---- images
        bgs = [m for m in self.materials if m.kind == config.KIND_BG]
        if bgs:
            from PIL import Image
            for m in bgs:
                t0 = time.time()
                try:
                    raw = Image.open(m.src)
                    raw.load()
                except Exception as e:  # noqa: BLE001
                    raise BuildError("L1", "cannot decode image %s" % m.rel, str(e))
                src = raw.convert("RGB")
                fitted, note = bc1.fit_image(src, (config.TARGET_W, config.TARGET_H), c.fit)
                log("L1", "[%s] %s  %dx%d  -> %s" % (m.kind, m.rel, src.size[0], src.size[1], note))
                levels = bc1.mip_chain(fitted)
                enc = bc1.encode_chain(levels, 2)
                if len(enc) != len(self.tex_mips):
                    raise BuildError("L1", "%s produced %d mip levels, the cooked shell has %d"
                                     % (m.rel, len(enc), len(self.tex_mips)))
                chain_path = os.path.join(norm, "%s.bc1chain" % m.name)
                with open(chain_path, "wb") as f:
                    for i, e in enumerate(enc):
                        if len(e) != self.tex_mips[i].size:
                            raise BuildError("L1", "mip%d of %s is %d B, shell slot is %d B"
                                             % (i, m.rel, len(e), self.tex_mips[i].size))
                        f.write(e)
                dec = bc1.decode_bc1(enc[0], config.TARGET_W, config.TARGET_H)
                import numpy as np
                q = bc1.quality(dec, np.asarray(fitted))
                q["mip_sha256"] = [sha256_bytes(e)[:16].upper() for e in enc]
                m.quality = q
                prev = ensure_dir(os.path.join(c.out_patch, "verify"))
                bc1.write_png(os.path.join(prev, "%s_preview.png" % m.name), dec[::2, ::2])
                m.note = note
                log("L1", "QUALITY: %s PSNR=%s dB MAE=%s 清晰度比=%s  (%s, %.1fs)"
                    % (m.name, q["psnr_db"], q["mae_s"], q["sharpness_s"], note, time.time() - t0))
                min_psnr = config.limit_min_psnr()
                if q["psnr"] < min_psnr:
                    if not c.force:
                        raise BuildError(
                            "L1", "image quality gate failed for %s: PSNR=%.2f dB < %.1f dB"
                            % (m.rel, q["psnr"], min_psnr),
                            "open %s and compare with the source; a value this low usually "
                            "means the encoder is broken. -Force overrides."
                            % os.path.join(prev, "%s_preview.png" % m.name))
                    log("L1", "WARN: %s passed only because of -Force (PSNR %.2f dB < %.1f)"
                        % (m.rel, q["psnr"], min_psnr))

        # ---- audio
        auds = [m for m in self.materials if m.kind != config.KIND_BG]
        total_sec = 0.0
        for m in auds:
            info = read_wav(m.src)
            ext = os.path.splitext(m.src)[1].lower()
            need = True
            reason = ""
            if info is not None:
                ok, why = compliance(info, config.AUDIO_RATE, config.AUDIO_MAX_CH, config.AUDIO_BITS)
                need = not ok
                reason = why
                log("L1", "[%s] %s  %s" % (m.kind, m.rel, info.describe()))
            else:
                reason = "not a RIFF/WAVE file (%s)" % (ext or "no extension")
                log("L1", "[%s] %s  not a readable WAV: %s" % (m.kind, m.rel, reason))

            out_wav = os.path.join(norm, "%s.wav" % m.name)
            if need:
                if not kit.ffmpeg:
                    raise BuildError("L1", "transcoding required for %s (%s) but ffmpeg is missing"
                                     % (m.rel, reason), FFMPEG_HELP)
                ch = info.channels if (info and 1 <= info.channels <= 2) else 2
                argv = [kit.ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                        "-i", m.src, "-vn", "-sn", "-dn", "-ar", str(config.AUDIO_RATE)]
                if ch == 2:
                    argv += ["-ac", "2"]
                argv += ["-c:a", "pcm_s16le", out_wav]
                log("L1", "  transcode (%s) -> PCM s16le / %d Hz / %dch" % (reason, config.AUDIO_RATE, ch))
                r = run(argv, log=log, stage="L1", timeout=900)
                if not r.ok or not os.path.isfile(out_wav):
                    raise BuildError("L1", "ffmpeg failed on %s" % m.rel, r.tail())
                log("L1", "  ffmpeg rc=%d (%.2fs)" % (r.rc, r.seconds))
            else:
                shutil.copy2(m.src, out_wav)
                log("L1", "  already compliant (%s) -> used as-is, no re-encode" % reason)

            fin = read_wav(out_wav)
            if fin is None:
                raise BuildError("L1", "produced file is not a readable WAV: %s" % out_wav)
            ok, why = compliance(fin, config.AUDIO_RATE, config.AUDIO_MAX_CH, config.AUDIO_BITS)
            if not ok:
                raise BuildError("L1", "audio material %s is still not compliant after "
                                       "normalisation: %s" % (m.rel, why), fin.describe())
            if fin.duration <= 0.0:
                raise BuildError("L1", "audio material %s has zero duration" % m.rel)
            total_sec += fin.duration
            m.audio = {"wav": out_wav, "channels": fin.channels, "rate": fin.rate,
                       "bits": fin.bits, "frames": fin.frames,
                       "duration": round(fin.duration, 6),
                       "payload_bytes": fin.size, "transcoded": bool(need),
                       "source_info": (info.describe() if info else "unreadable"),
                       "why": reason}
            m.payload_bytes = fin.size
            log("L1", "AUDIO: %s kind=%s %.3f s %d Hz %dch %d-bit payload=%s -> %s"
                % (m.name, m.kind, fin.duration, fin.rate, fin.channels, fin.bits,
                   human(fin.size), m.pkg))
        if auds:
            cap_s = config.limit_max_audio_seconds()
            log("L1", "audio total duration = %.2f s (limit %.0f s)" % (total_sec, cap_s))
            if total_sec > cap_s and not c.force:
                raise BuildError("L1", "total audio duration %.1f s exceeds the %.0f s limit"
                                 % (total_sec, cap_s),
                                 "re-run with -Force to override (PCM is uncompressed: "
                                 "48 kHz stereo is about 11.5 MB per minute)")

    # ================================================================= L2
    def l2(self) -> None:
        c, log, kit = self.c, self.log, self.kit
        assets = ensure_dir(os.path.join(c.work, "assets"))
        norm = os.path.join(c.work, "norm")
        ren = ensure_dir(os.path.join(c.work, "ren"))

        for m in self.materials:
            legacy_rel = os.path.join(config.legacy_rel_from_pkg(m.pkg)) + ".uasset"
            m.legacy_rel = legacy_rel.replace("\\", "/")
            dest_dir = ensure_dir(os.path.join(assets, os.path.dirname(legacy_rel)))
            if m.kind == config.KIND_BG:
                od = ensure_dir(os.path.join(ren, m.name))
                r = kit.da(["namerepl", self.tex_shell_ua, kit.usmap, od, m.obj,
                            os.path.basename(config.TEX_SHELL), m.pkg], log, "L2")
                if not r.ok:
                    raise BuildError("L2", "da-patch namerepl failed for %s" % m.name, r.tail())
                new_ua = os.path.join(od, m.obj + ".uasset")
                new_ux = os.path.join(od, m.obj + ".uexp")
                if not (os.path.isfile(new_ua) and os.path.isfile(new_ux)):
                    raise BuildError("L2", "namerepl produced no %s" % new_ua)
                raw = open(os.path.join(norm, "%s.bc1chain" % m.name), "rb").read()
                encs, off = [], 0
                for mp in self.tex_mips:
                    encs.append(raw[off:off + mp.size])
                    off += mp.size
                if off != len(raw):
                    raise BuildError("L2", "bc1 chain length mismatch for %s" % m.name)
                texture.replace_mips(new_ux, self.tex_mips, encs, log, "L2")
            else:
                wav = m.audio["wav"]
                od = ensure_dir(os.path.join(ren, m.name))
                r = kit.da(["sndmk", self.snd_shell_ua, kit.usmap, od, m.obj,
                            m.pkg, "PCM", wav], log, "L2")
                if not r.ok:
                    raise BuildError("L2", "da-patch sndmk failed for %s" % m.name, r.tail())
                new_ua = os.path.join(od, m.obj + ".uasset")
                new_ux = os.path.join(od, m.obj + ".uexp")
                if not (os.path.isfile(new_ua) and os.path.isfile(new_ux)):
                    raise BuildError("L2", "sndmk produced no %s" % new_ua)
                self._fix_zen_bulkmap(new_ua, os.path.getsize(wav), log, "L2")
                self._verify_soundwave_uexp(new_ux, m, log)

            shutil.copy2(new_ua, os.path.join(dest_dir, m.obj + ".uasset"))
            shutil.copy2(new_ux, os.path.join(dest_dir, m.obj + ".uexp"))
            shr = sha256_file(os.path.join(dest_dir, m.obj + ".uasset"))
            m.size_bytes = os.path.getsize(os.path.join(dest_dir, m.obj + ".uasset"))
            m.sha256 = shr
            log("L2", "[%s] %s -> %s  (%s uasset, uexp %s)"
                % (m.kind, m.name, m.legacy_rel, human(m.size_bytes),
                   human(os.path.getsize(os.path.join(dest_dir, m.obj + ".uexp")))))

    def _fix_zen_bulkmap(self, uasset: str, payload: int, log: Log, stage: str) -> None:
        """Zen FByteBulkData in the uexp is a 4-byte BulkDataMap index; retoc moves
        that table into the legacy uasset tail, so its SerialSize must match the
        real inline payload or the engine reads a stale length."""
        b = bytearray(open(uasset, "rb").read())
        needle = struct.pack("<q", 0x46) + struct.pack("<q", -1) + struct.pack("<q", 28)
        n = b.count(needle)
        if n != 1:
            raise BuildError(stage, "expected exactly 1 shell bulk-map record "
                                    "(SerialOffset=0x46,CookedIndex=-1,SerialSize=28), got %d" % n,
                             uasset)
        at = bytes(b).find(needle) + 16
        old = struct.unpack_from("<q", b, at)[0]
        struct.pack_into("<q", b, at, payload)
        open(uasset, "wb").write(bytes(b))
        log(stage, "  BULKMAP SerialSize %d -> %d (uasset 0x%X)" % (old, payload, at))

    def _verify_soundwave_uexp(self, uexp: str, m: Material, log: Log) -> None:
        b = open(uexp, "rb").read()
        ch = struct.unpack_from("<i", b, 0x06)[0]
        rate = struct.unpack_from("<i", b, 0x0A)[0]
        dur = struct.unpack_from("<f", b, 0x0E)[0]
        frames = struct.unpack_from("<f", b, 0x12)[0]
        a = m.audio
        bad = []
        if ch != a["channels"]:
            bad.append("NumChannels %d != %d" % (ch, a["channels"]))
        if rate != a["rate"]:
            bad.append("SampleRate %d != %d" % (rate, a["rate"]))
        if abs(dur - a["duration"]) > 0.01:
            bad.append("Duration %.3f != %.3f" % (dur, a["duration"]))
        if abs(frames - a["frames"]) > 1:
            bad.append("TotalSamples %.0f != %d" % (frames, a["frames"]))
        if len(b) != 26 + 8 + 16 + 4 + 8 + 4 + 4 + a["payload_bytes"] + 4 + 4 + 4:
            bad.append("uexp length %d does not match payload %d" % (len(b), a["payload_bytes"]))
        if bad:
            raise BuildError("L2", "built SoundWave for %s does not match its WAV" % m.name,
                             "; ".join(bad))
        log("L2", "  A3(local) OK: NumChannels=%d SampleRate=%d Duration=%.3f TotalSamples=%.0f"
            % (ch, rate, dur, frames))

    # ================================================================= L3
    def l3(self) -> None:
        c, log, kit = self.c, self.log, self.kit
        da_work = ensure_dir(os.path.join(c.work, "da"))
        carried = self._carried_da() if c.combined else {}

        by_kind: Dict[str, List[Material]] = {k: [] for k in config.KINDS}
        for m in self.materials:
            by_kind[m.kind].append(m)

        self.da_out: Dict[str, str] = {}
        self.da_rows: Dict[str, List[Tuple[str, str, str]]] = {}
        self.da_base_counts: Dict[str, int] = {}
        for tag, kind in (("DA_Backgrounds", config.KIND_BG), ("DA_BGM", config.KIND_BGM),
                          ("DA_Ambient", config.KIND_AMBIENT), ("DA_Sounds", config.KIND_SOUND)):
            base_ua = carried.get(tag) or self.da_base[tag]
            base_ux = os.path.splitext(base_ua)[0] + ".uexp"
            if not os.path.isfile(base_ux):
                raise BuildError("L3", "base DA uexp missing for %s" % tag, base_ux)
            cur_dir = ensure_dir(os.path.join(da_work, tag))
            cur_ua = os.path.join(cur_dir, os.path.basename(base_ua))
            shutil.copy2(base_ua, cur_ua)
            shutil.copy2(base_ux, os.path.splitext(cur_ua)[0] + ".uexp")
            base_count = self._count_da(cur_ua, tag)
            before = open(os.path.splitext(cur_ua)[0] + ".uexp", "rb").read()

            rows = by_kind.get(kind, [])
            if c.combined and rows:
                keep, repl = [], []
                for r in rows:
                    (repl if r.name.lower() in self._carried_names() else keep).append(r)
                for r in repl:
                    log("L3", "  UPGRADE: '%s' already exists in the carried build -> its asset "
                              "is rebuilt in place, no duplicate DA row" % r.name)
                    r.upgraded = True
                rows = keep
            if not rows and not carried.get(tag):
                log("L3", "%s: nothing to append" % tag)
            if rows and tag == "DA_Backgrounds":
                cur_ua = append_bg_rows(kit, cur_ua, cur_dir,
                                        [BgRow(r.key, r.pkg, r.obj) for r in rows],
                                        base_count, log, "L3")
            elif rows:
                cur_ua = append_audio_rows(kit, cur_ua, cur_dir,
                                           [AudioRow(r.kind, r.key, r.pkg, r.obj) for r in rows],
                                           log, "L3")

            after = open(os.path.splitext(cur_ua)[0] + ".uexp", "rb").read()
            if rows:
                stride = 34 if tag == "DA_Backgrounds" else 28
                off = 8 if tag == "DA_Backgrounds" else 6
                rows_off = 12 if tag == "DA_Backgrounds" else 10
                assert_append_only(before, after, off, stride, rows_off, len(rows),
                                   base_count, tag, log, "L3")
            self.da_out[tag] = cur_ua
            self.da_rows[tag] = [(r.key, r.pkg, r.obj) for r in rows]
            self.da_base_counts[tag] = base_count
            new_count = self._count_da(cur_ua, tag)
            log("L3", "%s: rows %d -> %d (+%d)" % (tag, base_count, new_count, len(rows)))
            if new_count != base_count + len(rows):
                raise BuildError("L3", "%s row count %d != %d + %d"
                                 % (tag, new_count, base_count, len(rows)))
            for r in rows:
                r.note = (r.note + " da_rows=%d" % new_count).strip()
        self.da_counts = {t: self._count_da(self.da_out[t], t) for t in self.da_out}
        log("L3", "final DA row counts: %s"
            % ", ".join("%s=%d" % (k, v) for k, v in sorted(self.da_counts.items())))

    def _count_da(self, uasset: str, tag: str) -> int:
        ux = os.path.splitext(uasset)[0] + ".uexp"
        b = open(ux, "rb").read()
        if tag == "DA_Backgrounds":
            return struct.unpack_from("<I", b, 8)[0]
        return native_audio_count(ux)

    def _carried_da(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        prev = self.c.prev_work
        if not prev:
            return out
        for tag, pkg in (("DA_Backgrounds", config.DA_BACKGROUNDS), ("DA_BGM", config.DA_BGM),
                         ("DA_Ambient", config.DA_AMBIENT), ("DA_Sounds", config.DA_SOUNDS)):
            p = os.path.join(prev, "legacy", config.legacy_rel_from_pkg(pkg) + ".uasset")
            if os.path.isfile(p):
                out[tag] = p
        return out

    def _carried_assets(self) -> List[Tuple[str, str]]:
        """(legacy_rel, abs path inside the previous work tree) for assets to carry.

        Assets this run rebuilds itself are excluded so the fresh build wins.
        """
        res: List[Tuple[str, str]] = []
        prev = self.c.prev_work
        if not prev:
            return res
        base = os.path.join(prev, "legacy")
        if not os.path.isdir(base):
            return res
        da_names = {"DA_Backgrounds", "DA_BGM", "DA_Ambient", "DA_Sounds"}
        mine = {m.name.lower() for m in self.materials}
        for root, _dirs, files in os.walk(base):
            for f in files:
                if not f.endswith(".uasset"):
                    continue
                stem = f[:-7]
                if stem in da_names or stem.lower() in mine:
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base).replace("\\", "/")
                res.append((rel, full))
        return res

    # ================================================================= L4
    def l4(self) -> None:
        c, log, kit = self.c, self.log, self.kit
        legacy = ensure_dir(os.path.join(c.work, "legacy"))

        # carry over previously built asset packages (must happen before assembly)
        if c.combined:
            n = 0
            for rel, src in self._carried_assets():
                dst = os.path.join(legacy, rel)
                ensure_dir(os.path.dirname(dst))
                shutil.copy2(src, dst)
                ux = os.path.splitext(src)[0] + ".uexp"
                if os.path.isfile(ux):
                    shutil.copy2(ux, os.path.splitext(dst)[0] + ".uexp")
                n += 1
            log("L4", "-Combined: carried over %d asset package(s) from the previous build" % n)
            self.carried_materials = []
            mine = {m.name.lower() for m in self.materials}
            for pm in self._prev_manifest.get("materials", []):
                if str(pm.get("name", "")).lower() in mine:
                    continue
                mm = Material(**{k: v for k, v in pm.items()
                                 if k in Material.__dataclass_fields__})
                mm.carried = True
                self.carried_materials.append(mm)
            log("L4", "-Combined: the previous build contributed %d material(s) to the report: %s"
                % (len(self.carried_materials),
                   ", ".join(x.name for x in self.carried_materials) or "<none>"))

        for m in self.materials:
            if m.carried:
                continue
            dst = os.path.join(legacy, m.legacy_rel)
            ensure_dir(os.path.dirname(dst))
            src_dir = os.path.join(c.work, "assets", os.path.dirname(m.legacy_rel))
            shutil.copy2(os.path.join(src_dir, m.obj + ".uasset"), dst)
            shutil.copy2(os.path.join(src_dir, m.obj + ".uexp"),
                         os.path.splitext(dst)[0] + ".uexp")
        for tag, ua in self.da_out.items():
            rel = config.legacy_rel_from_pkg(
                {"DA_Backgrounds": config.DA_BACKGROUNDS, "DA_BGM": config.DA_BGM,
                 "DA_Ambient": config.DA_AMBIENT, "DA_Sounds": config.DA_SOUNDS}[tag])
            dst = os.path.join(legacy, rel + ".uasset")
            ensure_dir(os.path.dirname(dst))
            shutil.copy2(ua, dst)
            shutil.copy2(os.path.splitext(ua)[0] + ".uexp", os.path.splitext(dst)[0] + ".uexp")

        files = 0
        for _r, _d, fs in os.walk(legacy):
            files += len(fs)
        log("L4", "legacy tree assembled: %d file(s) at %s" % (files, legacy))

        out_utoc = os.path.join(c.out_patch, c.game.container_base + config.PATCH_SUFFIX + ".utoc")
        kit.to_zen(legacy, out_utoc, log, "L4")
        stem = os.path.splitext(out_utoc)[0]
        for ext in ("pak", "ucas", "utoc"):
            p = stem + "." + ext
            if not os.path.isfile(p):
                raise BuildError("L4", "retoc produced no .%s" % ext, p)
        self.container = {
            "base": os.path.basename(stem),
            "files": {e: {"path": stem + "." + e, "bytes": os.path.getsize(stem + "." + e),
                          "sha256": sha256_file(stem + "." + e)} for e in ("pak", "ucas", "utoc")},
        }
        info = kit.info(out_utoc, log, "L4")
        log("L4", info.strip().replace("\n", "\n         "))
        m = re.search(r"chunks:\s*(\d+)", info)
        pk = re.search(r"packages:\s*(\d+)", info)
        self.container["chunks"] = int(m.group(1)) if m else -1
        self.container["packages"] = int(pk.group(1)) if pk else -1
        if self.container["packages"] != len(self.materials) + len(self.da_out) - \
                (len(self._carried_asset_names()) if c.combined else 0):
            log("L4", "NOTE: packages=%d, assets=%d, DA=%d (carried packages count too)"
                % (self.container["packages"], len(self.materials), len(self.da_out)))

        self._stage_paks_for_gates()
        self._gates()
        self._write_manifest()

    def _write_manifest(self) -> None:
        """Persist what this build produced so a later `-Combined` run can accumulate.

        `out_patch/work/manifest.json` is the ONLY state carried between runs; it is
        deleted together with the work tree once a run finishes.
        """
        allm = [m for m in self.materials if not m.carried] + list(self.carried_materials)
        man = {"tool": "CalaPlayerSrcmBuilder", "version": TOOL_VERSION,
               "top_folder": self.c.top_folder,
               "da_counts": getattr(self, "da_counts", {}),
               "materials": [asdict(m) for m in allm]}
        p = os.path.join(self.c.work, "manifest.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2, ensure_ascii=False)
        self.log("L4", "manifest written: %d material(s) available for a later -Combined run"
                 % len(allm))

    def _carried_names(self) -> set:
        return {str(m.get("name", "")).lower()
                for m in self._prev_manifest.get("materials", []) if m.get("name")}

    def _carried_asset_names(self) -> List[str]:
        return [os.path.splitext(os.path.basename(rel))[0] for rel, _ in self._carried_assets()]

    def _stage_paks_for_gates(self) -> None:
        c = self.c
        stage = ensure_dir(os.path.join(c.work, "stage_paks"))
        for f in sorted(os.listdir(self.native_paks)):
            hardlink_or_copy(os.path.join(self.native_paks, f),
                             os.path.join(stage, f), self.log, "L4")
        for ext in ("pak", "ucas", "utoc"):
            shutil.copy2(self.container["files"][ext]["path"],
                         os.path.join(stage, c.game.container_base + config.PATCH_SUFFIX + "." + ext))
        pure = ensure_dir(os.path.join(c.work, "stage_pure"))
        for ext in ("utoc", "ucas"):
            p = os.path.join(self.native_paks, "global." + ext)
            if os.path.isfile(p):
                hardlink_or_copy(p, os.path.join(pure, "global." + ext), self.log, "L4")
        for ext in ("pak", "ucas", "utoc"):
            shutil.copy2(self.container["files"][ext]["path"],
                         os.path.join(pure, c.game.container_base + config.PATCH_SUFFIX + "." + ext))
        self.stage_paks = stage
        self.stage_pure = pure

    def _gates(self) -> None:
        c, log, kit = self.c, self.log, self.kit

        # ---- A0 shell round-trip fidelity
        a0 = []
        for label, ua in (("texture_shell", self.tex_shell_ua), ("sound_shell", self.snd_shell_ua)):
            od = ensure_dir(os.path.join(c.work, "rt_%s" % label))
            r = kit.da(["roundtrip", ua, kit.usmap, od], log, "L4")
            ok = r.ok
            detail = []
            for ext in (".uasset", ".uexp"):
                a = ua.rsplit(".", 1)[0] + ext
                b = os.path.join(od, os.path.basename(a))
                same = os.path.isfile(b) and sha256_file(a) == sha256_file(b)
                ok = ok and same
                detail.append("%s=%s" % (ext, "identical" if same else "DIFFERS"))
            a0.append("%s: %s" % (label, " ".join(detail)))
        self.gate("A0", all("DIFFERS" not in x for x in a0),
                  "UAssetAPI write-back fidelity | " + " | ".join(a0))

        # ---- chunk-id ledger (A5)
        base_ids = {cid for cid, k in kit.list_chunks(
            os.path.join(self.native_paks, c.game.container_base + ".utoc"), log, "L4")
            if k == "ExportBundleData"}
        mine = kit.list_chunks(self.container["files"]["utoc"]["path"], log, "L4")
        bundles = [(cid, k) for cid, k in mine if k == "ExportBundleData"]
        hit = [cid for cid, _k in bundles if cid in base_ids]
        new = [cid for cid, _k in bundles if cid not in base_ids]
        log("L4", "LEDGER new(0-hit)=%d override(1-hit)=%d expected overrides=%d"
            % (len(new), len(hit), len(self.da_out)))
        self.ledger = {"new": sorted(new), "override": sorted(hit), "base_chunks": len(base_ids)}
        for cid, _k in bundles:
            log("L4", "  %s hits_in_base=%d" % (cid, 1 if cid in base_ids else 0))
        self.gate("A5", len(hit) == len(self.da_out),
                  "chunk-id ledger: %d brand-new package(s) with 0 hits in the native "
                  "container, %d deliberate DA override(s) (expected %d)"
                  % (len(new), len(hit), len(self.da_out)))

        # ---- A1/A2/A4 per audio material, straight out of the container
        a1, a2, a4 = [], [], []
        for m in self.materials:
            if m.kind == config.KIND_BG:
                continue
            pkg = m.pkg
            wav_out = os.path.join(c.out_patch, "verify",
                                   "%s_decoded_from_container.wav" % m.name)
            out = kit.tex_audio_out(self.stage_paks, pkg, wav_out, log, "L4")
            name = re.search(r"EXPORT name=(\S+) type=(\S+)", out)
            ok1 = bool(name) and name.group(1) == m.obj and name.group(2).endswith("USoundWave")
            a1.append("%s:%s" % (m.name, "ok" if ok1 else "BAD"))
            streaming = re.search(r"bStreaming=(\w+)", out)
            fmt = re.search(r'AudioFormat="([^"]+)"', out)
            nch = re.search(r"NumChunks=(\d+)", out)
            ds = re.search(r"chunk DataSize=(\d+) AudioDataSize=(\d+) actualBytes=(\d+)", out)
            ok2 = (streaming and streaming.group(1) == "True" and fmt and fmt.group(1) == "PCM"
                   and nch and nch.group(1) == "1" and ds
                   and ds.group(1) == ds.group(2) == ds.group(3)
                   and int(ds.group(3)) == m.audio["payload_bytes"])
            a2.append("%s:%s" % (m.name, "ok" if ok2 else "BAD"))
            same = os.path.isfile(wav_out) and verify_identity(wav_out, m.audio["wav"])
            src_sha = sha256_file(m.audio["wav"])[:16].upper() if same else "-"
            a4.append("%s:%s(%s)" % (m.name, "byte-identical" if same else "DIFFERS", src_sha))
            log("L4", "  A2 %s: %s" % (m.name, out.strip().splitlines()[-1]))
        if a1:
            self.gate("A1", all(x.endswith("ok") for x in a1),
                      "CUE4Parse reads every built asset as USoundWave | " + " ".join(a1))
            self.gate("A2", all(x.endswith("ok") for x in a2),
                      "bStreaming=True AudioFormat=PCM NumChunks=1 and the inline payload "
                      "length matches the WAV | " + " ".join(a2))
            self.gate("A4", all("byte-identical" in x for x in a4),
                      "decode-back from the container == the normalised WAV, byte for byte | "
                      + " ".join(a4))
        else:
            for g in ("A1", "A2", "A4"):
                self.gate(g, True, "skipped (no audio material)")

        # ---- A3 for audio (from the built uexp) + background payload check
        a3 = []
        for m in self.materials:
            if m.kind == config.KIND_BG:
                continue
            ux = os.path.join(c.work, "assets", os.path.dirname(m.legacy_rel), m.obj + ".uexp")
            b = open(ux, "rb").read()
            ch = struct.unpack_from("<i", b, 0x06)[0]
            rate = struct.unpack_from("<i", b, 0x0A)[0]
            dur = struct.unpack_from("<f", b, 0x0E)[0]
            fr = struct.unpack_from("<f", b, 0x12)[0]
            ok = (ch == m.audio["channels"] and rate == m.audio["rate"]
                  and abs(dur - m.audio["duration"]) <= 0.01
                  and abs(fr - m.audio["frames"]) <= 1)
            a3.append("%s:%dch/%dHz/%.3fs/%d" % (m.name, ch, rate, dur, int(fr)))
            if not ok:
                raise BuildError("L4", "A3 failed for %s" % m.name, a3[-1])
        self.gate("A3", True, "cooked USoundWave properties match the WAV | "
                  + (" ".join(a3) if a3 else "skipped (no audio material)"))

        # ---- A6: round-trip the DELIVERED container back out and check every byte
        od = ensure_dir(os.path.join(c.work, "rt_container"))
        kit.to_legacy(self.stage_pure, od, None, log, "L4")
        found = {}
        for root, _d, fs in os.walk(od):
            for f in fs:
                if f.endswith((".uasset", ".uexp")):
                    full = os.path.join(root, f)
                    found[os.path.relpath(full, od).replace("\\", "/")] = full
        a6 = []
        # (a) DA tables come back with the expected row counts and append-only shape
        for tag, ua in self.da_out.items():
            rel = config.legacy_rel_from_pkg(
                {"DA_Backgrounds": config.DA_BACKGROUNDS, "DA_BGM": config.DA_BGM,
                 "DA_Ambient": config.DA_AMBIENT, "DA_Sounds": config.DA_SOUNDS}[tag])
            got = found.get(rel.replace("\\", "/") + ".uexp")
            if not got:
                raise BuildError("L4", "A6: %s.uexp did not come back out of the container" % tag,
                                 "extracted %d files" % len(found))
            n = self._count_da(got.replace(".uexp", ".uasset"), tag)
            if n != self.da_counts[tag]:
                raise BuildError("L4", "A6: %s round-tripped with %d rows, expected %d"
                                 % (tag, n, self.da_counts[tag]))
            a6.append("%s=%d" % (tag, n))
        # (b) every built asset package comes back byte-identical
        for m in self.materials:
            rel = m.legacy_rel
            got_ux = found.get(rel[:-7] + ".uexp")
            want = os.path.join(c.work, "assets", os.path.dirname(m.legacy_rel), m.obj + ".uexp")
            if not got_ux:
                raise BuildError("L4", "A6: %s did not come back out of the container" % rel,
                                 "extracted %d files" % len(found))
            if sha256_file(got_ux) != sha256_file(want):
                raise BuildError("L4", "A6: %s round-tripped with different bytes" % rel,
                                 "%s vs %s" % (sha16(got_ux), sha16(want)))
            a6.append("%s=identical" % m.name)
        self.gate("A6", True,
                  "container round-trip: DA row counts hold and every built asset uexp is "
                  "byte-identical | " + " ".join(a6))

        # ---- A7: the appended rows really NAME what we intended
        #      (display name => DA map key, soft path => package + object).
        #      This is the gate that protects non-ASCII dropdown names: A6 only
        #      counts rows and hashes asset bytes, it never looks at the key text.
        a7 = []
        for tag, _ua in self.da_out.items():
            rows = self.da_rows.get(tag) or []
            if not rows:
                continue
            pkg = {"DA_Backgrounds": config.DA_BACKGROUNDS, "DA_BGM": config.DA_BGM,
                   "DA_Ambient": config.DA_AMBIENT, "DA_Sounds": config.DA_SOUNDS}[tag]
            rel = config.legacy_rel_from_pkg(pkg).replace("\\", "/")
            got_ua = found.get(rel + ".uasset")
            got_ux = found.get(rel + ".uexp")
            if not (got_ua and got_ux):
                raise BuildError("L4", "A7: %s did not come back out of the container" % tag)
            names = self._probe_names(got_ua)
            data = open(got_ux, "rb").read()
            if tag == "DA_Backgrounds":
                stride, rows_off = 34, 12
            else:
                stride, rows_off = 28, 10
            base = self.da_base_counts[tag]
            for i, (key, kpkg, kobj) in enumerate(rows):
                off = rows_off + stride * (base + i)
                ki = struct.unpack_from("<I", data, off)[0]
                pi = struct.unpack_from("<I", data, off + (10 if stride == 34 else 8))[0]
                ai = struct.unpack_from("<I", data, off + (18 if stride == 34 else 16))[0]
                for what, idx, want in (("key", ki, key), ("pkg", pi, kpkg), ("obj", ai, kobj)):
                    if idx >= len(names):
                        raise BuildError("L4", "A7: %s row %d %s index %d out of range (%d names)"
                                         % (tag, base + i, what, idx, len(names)))
                    if names[idx] != want:
                        raise BuildError("L4", "A7: %s row %d %s is %r, expected %r"
                                         % (tag, base + i, what, names[idx], want),
                                         "the display name / soft path did not survive the "
                                         "container round-trip")
                a7.append("%s#%d='%s'" % (tag, base + i, key))
        if a7:
            self.gate("A7", True,
                      "DA rows in the container resolve to the intended display names and "
                      "soft paths (non-ASCII supported) | " + " ".join(a7[:8])
                      + (" …" if len(a7) > 8 else ""))

    def _probe_names(self, uasset: str) -> List[str]:
        r = self.kit.da(["probe", uasset, self.kit.usmap], self.log, "L4")
        if not r.ok:
            raise BuildError("L4", "da-patch probe failed on %s" % uasset, r.tail())
        out: List[str] = []
        for line in r.out.splitlines():
            m = re.match(r"^\s*name\[(\d+)\] = (.*)$", line)
            if m:
                out.append(m.group(2))
        if not out:
            raise BuildError("L4", "could not read the name table of %s" % uasset, r.tail())
        return out

    def _locked_patch_files(self) -> List[str]:
        """Read-only probe: a _P file we cannot even open for writing is held by
        another process -- almost always the game itself."""
        out = []
        for _ext, p in sorted(self.c.game.patch_files.items()):
            try:
                f = open(p, "rb+")
                f.close()
            except OSError:
                out.append(os.path.basename(p))
        return out

    # ================================================================= L5
    def l5(self) -> None:
        c, log = self.c, self.log
        paks = c.game.paks_dir
        for name in self._locked_patch_files():
            raise BuildError(
                "L5", "the game folder is in use: %s is locked" % name,
                "请先关闭 CalaPlayer（游戏）再运行安装 / close the game first.\n"
                "      Nothing was written; the game folder is untouched.")
        backup = ensure_dir(os.path.join(c.out_patch, "_prev_container"))
        moved: List[Tuple[str, str]] = []
        copied: List[str] = []
        try:
            # 1) back up whatever _P is installed
            for ext, p in sorted(c.game.patch_files.items()):
                dst = os.path.join(backup, os.path.basename(p))
                try:
                    shutil.move(p, dst)
                except OSError as e:
                    raise BuildError("L5", "cannot move %s out of the game folder"
                                     % os.path.basename(p),
                                     "%s\n      -> the game is most likely still running."
                                     " 请先关闭游戏再试 / close the game first." % e)
                moved.append((p, dst))
                log("L5", "backed up installed patch: %s -> %s" % (os.path.basename(p), backup))
            # 2) copy ours in
            for ext in ("pak", "ucas", "utoc"):
                src = self.container["files"][ext]["path"]
                dst = os.path.join(paks, os.path.basename(src))
                try:
                    shutil.copy2(src, dst)
                except OSError as e:
                    raise BuildError("L5", "cannot write %s into the game folder"
                                     % os.path.basename(dst),
                                     "%s\n      -> check free disk space and that the game is "
                                     "closed." % e)
                copied.append(dst)
                log("L5", "deployed %s (%s)" % (os.path.basename(dst), human(os.path.getsize(dst))))
            self.deployed = True
            # 3) read back from the REAL game folder
            self._verify_deployed(paks)
            self.rollback = {"moved_away": [os.path.basename(a) for a, _ in moved],
                             "restored": False, "result": "not needed"}
        except BaseException:
            log("L5", "ERROR after touching the game folder -> automatic rollback")
            self._rollback(moved, copied, paks, log)
            raise

    def _verify_deployed(self, paks: str) -> None:
        c, log, kit = self.c, self.log, self.kit
        log("L5", "re-reading the container straight from the real game folder")
        for m in self.materials:
            if m.kind == config.KIND_BG:
                out = kit.tex_dump(paks, m.pkg, os.path.join(c.work, "verify_live"), log, "L5")
                mm = texture.parse_mips(out)
                want = m.quality.get("mip_sha256") or []
                got = [x.sha256 for x in mm]
                if len(got) != len(want) or any(a != b for a, b in zip(got, want)):
                    raise BuildError("L5", "deployed background %s does not match what we built"
                                     % m.name,
                                     "live mips=%s expected=%s" % (got[:4], want[:4]))
                log("L5", "  %s all %d mip hashes OK (mip0 %s)" % (m.name, len(got), got[0]))
            else:
                wav = os.path.join(c.out_patch, "verify", "%s_live_check.wav" % m.name)
                out = kit.tex_audio_out(paks, m.pkg, wav, log, "L5")
                if not verify_identity(wav, m.audio["wav"]):
                    raise BuildError("L5", "deployed audio %s does not decode back to the source WAV"
                                     % m.name, out.strip().splitlines()[-1])
                log("L5", "  %s decode-back byte-identical OK" % m.name)
        # DA row counts straight from the live folder
        for tag in self.da_out:
            pkg = {"DA_Backgrounds": config.DA_BACKGROUNDS, "DA_BGM": config.DA_BGM,
                   "DA_Ambient": config.DA_AMBIENT, "DA_Sounds": config.DA_SOUNDS}[tag]
            od = ensure_dir(os.path.join(c.work, "verify_live_da", tag))
            kit.to_legacy(paks, od, pkg.rsplit("/", 1)[-1], log, "L5")
            hit = None
            for root, _d, fs in os.walk(od):
                for f in fs:
                    if f == pkg.rsplit("/", 1)[-1] + ".uasset":
                        hit = os.path.join(root, f)
            if not hit:
                raise BuildError("L5", "cannot read %s back from the live game folder" % tag)
            n = self._count_da(hit, tag)
            if n != self.da_counts[tag]:
                raise BuildError("L5", "live %s has %d rows, expected %d" % (tag, n, self.da_counts[tag]))
            log("L5", "  %s live rows = %d OK" % (tag, n))
        log("L5", "game-folder read-back verification PASSED")

    def _rollback(self, moved: List[Tuple[str, str]], copied: List[str], paks: str,
                  log: Log) -> None:
        """Undo whatever L5 had done.  We only ever delete a file whose bytes are
        exactly the ones we copied, so we can never destroy something else."""
        try:
            for ext in ("pak", "ucas", "utoc"):
                dst = os.path.join(paks, os.path.basename(self.container["files"][ext]["path"]))
                if not os.path.isfile(dst):
                    continue
                if sha256_file(dst) == self.container["files"][ext]["sha256"]:
                    os.remove(dst)
                    log("L5", "  removed %s (ours)" % os.path.basename(dst))
                else:
                    log("L5", "  leaving %s alone: it is not the file we copied"
                        % os.path.basename(dst))
            for orig, bak in moved:
                shutil.move(bak, orig)
            self.deployed = False
            self.rollback = {"moved_away": [os.path.basename(a) for a, _ in moved],
                             "restored": True, "result": "restored to the pre-install state"}
            log("L5", "rolled back: removed our container and restored %d file(s)" % len(moved))
        except Exception as e:  # noqa: BLE001
            self.rollback = {"moved_away": [os.path.basename(a) for a, _ in moved],
                             "restored": False, "result": "ROLLBACK FAILED: %s" % e}
            log("L5", "ROLLBACK FAILED: %s" % e)

    # ================================================================= bundle
    def write_bundle(self) -> None:
        c = self.c
        if not c.out_patch or c.game is None:
            return
        paks_default = c.game.paks_dir
        base = c.game.container_base + config.PATCH_SUFFIX
        install = INSTALL_PS1.replace("@@BASE@@", base).replace("@@PAKS@@", paks_default)
        uninstall = UNINSTALL_PS1.replace("@@BASE@@", base).replace("@@PAKS@@", paks_default)
        for name, text in (("install.ps1", install), ("uninstall.ps1", uninstall)):
            with open(os.path.join(c.out_patch, name), "w", encoding="ascii",
                      newline="\r\n") as f:
                f.write(text)
        with open(os.path.join(c.out_patch, "README.md"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(self._readme())
        with open(os.path.join(c.out_patch, "deploy.json"), "w", encoding="utf-8") as f:
            json.dump({"paks_dir": paks_default, "container_base": base}, f, indent=2)
        self.log("L5", "wrote install.ps1 / uninstall.ps1 / README.md / deploy.json")

    def _readme(self) -> str:
        c = self.c
        da_counts = getattr(self, "da_counts", {})
        n_bg = sum(1 for m in self.materials if m.kind == config.KIND_BG)
        n_au = len(self.materials) - n_bg
        n_up = sum(1 for m in self.materials if m.upgraded)
        lines = [
            "# CalaPlayer static patch bundle (`%s`)" % c.game.container_base,
            "",
            "Built by CalaPlayerSrcmBuilder %s at %s" % (TOOL_VERSION, time.strftime("%Y-%m-%d %H:%M:%S")),
            "Source material folder: `%s`" % os.path.abspath(c.srcm_arg),
            "Target game Paks folder (default): `%s`" % c.game.paks_dir,
            "",
            "## What is inside",
            "",
            "| item | value |",
            "|---|---|",
            "| backgrounds | %d |" % n_bg,
            "| audio (BGM + Sound + Ambient) | %d |" % n_au,
            "| carried over from the previous build (-Combined) | %d |" % len(self.carried_materials),
            "| rebuilt in place (-Combined upgrade) | %d |" % n_up,
            "| DA rows | %s |" % ", ".join("%s=%d" % (k, v) for k, v in sorted(da_counts.items())),
            "| container | `%s.{pak,ucas,utoc}` |" % c.game.container_base + config.PATCH_SUFFIX,
            "",
            "## Install / 安装",
            "",
            "```powershell",
            "powershell -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1",
            "# or a different Paks folder / 指定别的 Paks 目录:",
            "powershell -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 -Paks \"D:\\path\\to\\CalaPlayer\\Content\\Paks\"",
            "```",
            "",
            "## Uninstall / 回滚",
            "",
            "```powershell",
            "powershell -NoProfile -ExecutionPolicy Bypass -File .\\uninstall.ps1",
            "```",
            "",
            "`install.ps1` first MOVES the currently installed `_P` container into",
            "`_prev_container\\`, then copies this one in.  `uninstall.ps1` removes this",
            "one and puts the previous container back, so rollback == the state before",
            "the install (not the vanilla game).",
            "",
            "## Materials / 素材清单",
            "",
            "| kind | source | logical name | dropdown name | package |",
            "|---|---|---|---|---|",
        ]
        for m in self.materials:
            lines.append("| %s | %s | %s | %s | `%s` |"
                         % (m.kind, m.rel, m.name, m.key, m.pkg))
        for m in self.carried_materials:
            lines.append("| %s | %s | %s | %s | `%s` |"
                         % (m.kind, m.rel + " (carried)", m.name, m.key, m.pkg))
        lines += ["", "## Notes", ""]
        lines.append("- Backgrounds are re-encoded to 1920x1080 DXT1 (BC1), 11 mip levels.")
        lines.append("- Audio is embedded as uncompressed PCM s16le / 48 kHz inside a "
                     "streaming USoundWave; the payload is the RIFF/WAVE file itself.")
        if any(m.note.startswith("contain") for m in self.materials):
            lines.append("- `contain` fit was used: images are letterboxed with (18,18,22) bars.")
        lines.append("- Editor thumbnails for new backgrounds intentionally still show a "
                     "native sprite (v1 limitation, accepted): the big preview and PLAY are correct.")
        lines.append("- No native DataAsset row was modified: rows are appended only.")
        for w in self.c.warnings:
            lines.append("- WARNING: " + w)
        return "\n".join(lines) + "\n"

    # ================================================================= report
    def report(self, ok: bool, error: Optional[str] = None) -> Dict:
        c = self.c
        untouched = None
        native_now = {}
        native_paks = getattr(self, "native_paks", None)
        hashes = getattr(self, "native_hashes", None)
        if hashes and native_paks and os.path.isdir(native_paks):
            # None = "this run never even staged the natives" (it failed before that),
            # so nothing could have been written.  True = verified unchanged.
            for f in sorted(os.listdir(native_paks)):
                p = os.path.join(native_paks, f)
                native_now[f] = {"bytes": os.path.getsize(p), "sha256": sha256_file(p)}
            untouched = native_now == hashes
        rep = {
            "tool": "CalaPlayerSrcmBuilder", "version": TOOL_VERSION,
            "ok": bool(ok), "error": error,
            "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._t0)),
            "seconds": round(time.time() - self._t0, 2),
            "params": {"paks": c.paks_arg, "srcm": c.srcm_arg, "fit": c.fit, "force": c.force,
                       "dry_run": c.dry_run, "combined": c.combined,
                       "ffmpeg": c.ffmpeg, "kit": (self.kit.root if self.kit else None)},
            "resolved": {"paks_dir": (c.game.paks_dir if c.game else None),
                         "out_patch": c.out_patch, "container_base":
                             (c.game.container_base if c.game else None)},
            "stages": self.stages,
            "materials": [asdict(m) for m in self.materials],
            "carried_materials": [asdict(m) for m in self.carried_materials],
            "da_counts": getattr(self, "da_counts", {}),
            "gates": self.gates,
            "ledger": getattr(self, "ledger", {}),
            "container": self.container,
            "deployed": self.deployed,
            "rollback": self.rollback,
            "native_containers_untouched": untouched,
            "warnings": c.warnings,
        }
        return rep

    # ================================================================= run
    def run(self) -> Dict:
        c, log = self.c, self.log
        try:
            self._stage("L0", self.l0)
            if not self.materials:
                raise BuildError("L0", "no usable material found in srcm",
                                 "put images in bg\\ and audio in BGM\\ Sound\\ Ambient\\")
            self._stage("L1", self.l1)
            self._stage("L2", self.l2)
            self._stage("L3", self.l3)
            self._stage("L4", self.l4)
            if c.dry_run or not c.deploy:
                log("L4", "DRY RUN: the game folder was NOT touched. Deliverable is in %s"
                    % c.out_patch)
                self.deployed = False
            else:
                self._stage("L5", self.l5)
            self.write_bundle()
            self._write_log_copy()
            rep = self.report(True)
            return rep
        except BaseException as e:  # noqa: BLE001
            msg = str(e)
            log("ERR", msg)
            self.write_bundle()
            self._write_log_copy()
            rep = self.report(False, msg)
            raise
        finally:
            self._tidy_state()

    def _tidy_state(self) -> None:
        """Decide what happens to the carried-over build state.

        `out_patch\\work\\manifest.json` + the legacy tree in the same folder are the
        ONLY state a later `-Combined` run accumulates on.  A run that fails before
        writing its manifest must NOT throw the previous state away -- otherwise a
        single failed run would silently lose everything accumulated so far.
        """
        c = self.c
        if c.keep_work or not c.work or not c.prev_work:
            return
        if not os.path.isdir(c.prev_work):
            return
        if os.path.isfile(os.path.join(c.work, "manifest.json")):
            rmtree(c.prev_work)                     # this run produced valid state
            return
        rmtree(c.work)
        os.rename(c.prev_work, c.work)
        self.log("L0", "this run produced no build state -> kept the previous one at %s"
                 % c.work)

    def _write_log_copy(self) -> None:
        src = self.log.path
        if src and os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(self.c.out_patch, "build.log"))
            except Exception:
                pass


# --------------------------------------------------------------------------
INSTALL_PS1 = r"""# CalaPlayer static _P patch - installer (ASCII only)
# Run with:  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
param(
    [string]$Paks = "@@PAKS@@"
)
$ErrorActionPreference = "Stop"
$base = "@@BASE@@"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path $Paks)) { Write-Host "FATAL: Paks folder not found: $Paks"; exit 3 }
$prev = Join-Path $here "_prev_container"
New-Item -ItemType Directory -Force -Path $prev | Out-Null

foreach ($ext in @("pak","ucas","utoc")) {
    $cur = Join-Path $Paks "$base.$ext"
    if (Test-Path $cur) {
        $dst = Join-Path $prev "$base.$ext"
        Move-Item -LiteralPath $cur -Destination $dst -Force
        Write-Host "backed up existing $base.$ext -> _prev_container"
    }
}
foreach ($ext in @("pak","ucas","utoc")) {
    $src = Join-Path $here "$base.$ext"
    if (-not (Test-Path $src)) { Write-Host "FATAL: missing $src"; exit 4 }
    Copy-Item -LiteralPath $src -Destination (Join-Path $Paks "$base.$ext") -Force
    Write-Host "installed $base.$ext"
}
Write-Host ""
Write-Host "DONE. Roll back with: powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1"
"""

UNINSTALL_PS1 = r"""# CalaPlayer static _P patch - uninstaller / rollback (ASCII only)
# Run with:  powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
param(
    [string]$Paks = "@@PAKS@@"
)
$ErrorActionPreference = "Stop"
$base = "@@BASE@@"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$prev = Join-Path $here "_prev_container"
if (-not (Test-Path $Paks)) { Write-Host "FATAL: Paks folder not found: $Paks"; exit 3 }

foreach ($ext in @("pak","ucas","utoc")) {
    $cur = Join-Path $Paks "$base.$ext"
    if (Test-Path $cur) { Remove-Item -LiteralPath $cur -Force; Write-Host "removed $base.$ext" }
}
$restored = 0
if (Test-Path $prev) {
    foreach ($ext in @("pak","ucas","utoc")) {
        $b = Join-Path $prev "$base.$ext"
        if (Test-Path $b) {
            Copy-Item -LiteralPath $b -Destination (Join-Path $Paks "$base.$ext") -Force
            $restored++
            Write-Host "restored $base.$ext from _prev_container"
        }
    }
}
if ($restored -eq 0) { Write-Host "no previous container to restore: the game is back to vanilla" }
Write-Host ""
Write-Host "DONE. Rolled back to the pre-install state."
"""


def build(paks: str, srcm: str, log_path: str, **kw) -> Dict:
    reconfigure_stdio()
    ctx = Ctx(paks_arg=paks, srcm_arg=srcm, **kw)
    log = Log(path=log_path)
    b = Builder(ctx, log)
    try:
        rep = b.run()
    finally:
        log.close()
    return rep
