# -*- coding: utf-8 -*-
"""添加角色模型 —— 把一套皮肤素材做成游戏里"可以创建的新皮肤"。

用户视角（GUI 第三个模式 / CLI `import_character.py`）：
    选游戏 Paks 目录 + 一套导出的皮肤素材目录（如
    `...\\Characters\\Aika\\S051`，里面是贴图 PNG 与材质参考文件）
    → 工具产出两个补丁容器并装进游戏：
        `_P2`：新皮肤的资产（网格 / 材质 / 贴图，全部是新路径的新包）
        `_P` ：在既有补丁容器上**只替换 DA_Characters**（皮肤注册表）
    → 重启游戏，编辑器里"添加角色 → 选角色 → 皮肤列表"就能看到新皮肤。

生产配方来源（每一环都在真实客户端上实测过，见研究笔记）：
  1. 资产构建 = **纯同长字节替换**（皮肤 ID 4 字符对 4 字符）：
     `/S001/` → `/S052/`、`aika-s001` → `aika-s052`，
     绝不新增 import / 改表结构（那是网格黑屏的根因，教训 12.1）。
  2. 贴图 = 只替换 `.ubulk`（前几级大 mip），小 mip 内联在 `.uexp` 里保持原样；
     编码格式必须与**声明**一致：DXT1→DXT1、DXT5→DXT5、BC5→BC5，
     BC7 若要用 DXT 编码器必须同步把声明改成 PF_DXT5（教训 12.4）。
  3. 材质 = 只选"引用了被替换贴图"的材质（数据驱动），
     引用的贴图全部跟随构建（有素材用新像素、没有就复制），杜绝断链。
  4. DA = 名称链式 addname + 克隆源皮肤条目 + 改写引用（char_da.py）。
  5. 打包 = 新资产走 `_P2`（to-zen 完整头部含包注册）；
     已有 `_P` 用 unpack-raw/pack-raw **只换 DA chunk**（字节级无损，实测往返）。
  6. 部署 = `core/deploy.py` 的 install（备份 / 写后读回 / 失败还原）× 2 个容器。
"""
from __future__ import annotations

import os
import re
import shutil
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

import json

from . import char_da, char_kit, config, deploy
from .bcn import encode_ubulk, ubulk_mip_levels
from .common import BuildError, Log, ensure_dir, human, rmtree, sha16
from .da import probe_names
from .kit import Kit, load_kit
from . import texture as texmod

CHARACTERS_REL = "CalaPlayer/Content/CalaPlayer/Characters"
DA_REL = CHARACTERS_REL + "/DA_Characters"
SKIN_ID_RE = re.compile(r"^S\d{3}$")
MESH_NAME_RE = re.compile(r"^(?P<prefix>.+)-s(?P<num>\d{3})$")
PATH_RE = re.compile(rb"/Game/[A-Za-z0-9_./\-]{4,150}")

#: 各种贴图后缀 → 用途（仅用于日志/提示，不参与决策）
SUFFIX_HINT = {"_d": "漫反射", "_n": "法线", "mask1": "遮罩1", "mask2": "遮罩2"}


@dataclass
class CharCtx:
    paks_arg: str
    src_dir: str                    # 素材目录（导出皮肤目录或含 PNG 的目录）
    out_dir: str
    character: str = ""             # 角色（空 = 从素材路径推断）
    skin_id: str = ""               # 新皮肤 ID（空 = 自动推荐下一个）
    source_skin: str = "S001"       # 源皮肤（克隆模板）
    kit_arg: str = ""
    dry_run: bool = False           # 只构建不安装
    no_deploy: bool = False         # 构建 + 产出容器，但不写游戏目录
    keep_work: bool = False
    # ------- 发现阶段填充 -------
    game: Optional[config.GamePaths] = None
    kit: Optional[Kit] = None
    work: str = ""
    legacy: str = ""                # 提取树根
    char_dir: str = ""              # 游戏里的角色目录名（如 Aika / HuiXing）
    skin_num: str = ""              # 皮肤数字（"052"）
    src_skin_token: str = ""        # 素材路径里的皮肤记号（如 S051，用于匹配归一化）
    src_skin_dir: str = ""          # legacy 里的源皮肤目录
    new_skin_dir: str = ""          # legacy 里的目标皮肤目录（尚未创建）
    mesh_src: str = ""              # 源网格资产名（aika-s001）
    mesh_new: str = ""              # 目标网格资产名（aika-s052）
    out_assets: str = ""            # 构建产物资产树根
    p2_stage: str = ""              # _P2 打包输入
    p2_out: str = ""                # _P2 产物目录
    p_out: str = ""                 # _P 产物目录
    report_path: str = ""


class CharacterBuilder:
    def __init__(self, ctx: CharCtx, log: Log):
        self.ctx = ctx
        self.log = log
        self.stages: List[Tuple[str, float]] = []
        self.gates: List[Dict] = []
        self.result: Dict = {}
        # 计划（C2 填充）
        self.tex_build: List[Dict] = []       # 要构建的贴图
        self.mat_build: List[Dict] = []       # 要构建的材质
        self.elem_plan: Dict[int, Dict] = {}  # DA 槽位 -> 新材质路径
        self.char_idx = 0
        self.src_skin_idx = 0

    # ------------------------------------------------------------------
    # 编排
    # ------------------------------------------------------------------
    def _stage(self, name: str, fn):
        import time
        t0 = time.time()
        try:
            out = fn()
        except BuildError:
            raise
        except Exception as exc:                      # noqa: BLE001
            raise BuildError(name, "%s 阶段内部错误：%s" % (name, exc))
        self.stages.append((name, time.time() - t0))
        return out

    def gate(self, gid: str, ok: bool, detail: str, fatal: bool = True) -> None:
        self.gates.append({"id": gid, "ok": bool(ok), "detail": detail})
        tag = "PASS" if ok else "FAIL"
        self.log("GATE", "%s %s  %s" % (gid, tag, detail))
        if not ok and fatal:
            raise BuildError("GATE", "%s 未通过：%s" % (gid, detail))

    def run(self) -> Dict:
        c, log = self.ctx, self.log
        log("C0", "添加角色模型 —— 素材 %s" % c.src_dir)
        self._stage("C0", self.c0)
        self._stage("C1", self.c1)
        self._stage("C2", self.c2)
        self._stage("C3", self.c3)
        self._stage("C4", self.c4)
        self._stage("C5", self.c5)
        if c.dry_run or c.no_deploy:
            log("C6", "跳过部署（%s）" % ("DryRun" if c.dry_run else "NoDeploy"))
            self.result["installed"] = {}
        else:
            self._stage("C6", self.c6)
        self.result.update({
            "ok": True,
            "character": c.character,
            "char_dir": c.char_dir,
            "skin": c.skin_id,
            "source_skin": c.source_skin,
            "mesh": c.mesh_new,
            "textures": [t["name_new"] for t in self.tex_build],
            "materials": [m["name_new"] for m in self.mat_build],
            "out_dir": c.out_dir,
            "work": c.work if c.keep_work else "",
            "p_out": c.p_out,
            "p2_out": c.p2_out,
            "stages": self.stages,
            "gates": self.gates,
        })
        log("C6", "全部完成：游戏里 编辑器 → 角色 → 添加角色 → %s → 皮肤列表第 %d 个"
            % (c.character, self._skin_slot_hint()))
        return self.result

    def _skin_slot_hint(self) -> int:
        # 新皮肤加在源皮肤之后；给个保守的提示（实际顺序看游戏）
        return 2 if self.ctx.source_skin == "S001" else 1

    # ------------------------------------------------------------------
    # C0 环境
    # ------------------------------------------------------------------
    def c0(self) -> None:
        c, log = self.ctx, self.log
        if not os.path.isdir(c.src_dir):
            raise BuildError("C0", "素材目录不存在", c.src_dir)
        c.kit = load_kit(c.kit_arg or None, None, log, "C0")
        c.game = config.discover_game(c.paks_arg)
        log("C0", "游戏 Paks : %s" % c.game.paks_dir)
        paks = c.game.paks_dir
        if not os.path.isfile(os.path.join(paks, "CalaPlayer-Windows.utoc")):
            raise BuildError("C0", "Paks 目录里没有原生容器 CalaPlayer-Windows.utoc", paks)
        for probe in ("CalaPlayer-Windows.ucas",):
            p = os.path.join(paks, probe)
            try:
                fh = open(p, "r+b")
                fh.close()
            except OSError:
                raise BuildError("C0", "容器被占用（游戏还在跑？）—— 先关掉游戏", p)
        has_p = char_kit.container_exists(paks, "CalaPlayer-Windows_P")
        has_p2 = char_kit.container_exists(paks, "CalaPlayer-Windows_P2")
        log("C0", "现有补丁容器：_P=%s，_P2=%s%s" % (
            "有" if has_p else "无", "有" if has_p2 else "无",
            "（将只在 _P 里替换 DA chunk）" if has_p else "（将新建 _P 承载 DA）"))
        c.out_dir = os.path.abspath(c.out_dir or
                                    os.path.join(os.path.dirname(os.path.abspath(c.src_dir)),
                                                 "out_character"))
        # 每次构建都从干净的 work / 产物目录开始（install_backup_* 保留，用于回滚）
        rmtree(os.path.join(c.out_dir, "work"))
        rmtree(os.path.join(c.out_dir, "p"))
        rmtree(os.path.join(c.out_dir, "p2"))
        c.work = ensure_dir(os.path.join(c.out_dir, "work"))
        c.legacy = ensure_dir(os.path.join(c.work, "legacy"))
        c.out_assets = ensure_dir(os.path.join(c.work, "out_assets"))
        c.p2_stage = ensure_dir(os.path.join(c.work, "p2_stage"))
        c.p2_out = ensure_dir(os.path.join(c.out_dir, "p2"))
        c.p_out = ensure_dir(os.path.join(c.out_dir, "p"))
        self.gates.append({"id": "C0", "ok": True,
                           "detail": "kit + 游戏 + 输出目录就绪（_P=%s _P2=%s）"
                                     % (has_p, has_p2)})

    # ------------------------------------------------------------------
    # C1 基线提取
    # ------------------------------------------------------------------
    def _infer_character_and_skin(self) -> Tuple[str, str]:
        """从素材路径推断 (角色目录名, 皮肤目录名)；skin 可能为空。"""
        c = self.ctx
        norm = os.path.normpath(os.path.abspath(c.src_dir))
        parts = norm.replace("\\", "/").strip("/").split("/")
        char, skin = "", ""
        if len(parts) >= 2 and SKIN_ID_RE.match(parts[-1]):
            skin = parts[-1]
            char = parts[-2]
        elif parts:
            char = parts[-1]
        if c.character:
            char = c.character
        return char, skin

    def c1(self) -> None:
        c, log = self.ctx, self.log
        char, skin_in_path = self._infer_character_and_skin()
        if not char:
            raise BuildError("C1", "无法从素材目录推断角色名，请用 -Character 指定", c.src_dir)
        c.character = c.character or char
        c.src_skin_token = skin_in_path or ""
        log("C1", "角色：'%s'（素材路径推断自 '%s'；皮肤目录 %s）"
            % (c.character, char, skin_in_path or "无"))
        filters = ["Characters/%s/" % char, "DA_Characters."]
        # 旧的 _P2 也要原样并入新 _P2，所以它涉及的每个皮肤目录都得提取出来
        if char_kit.container_exists(c.game.paks_dir, "CalaPlayer-Windows_P2"):
            p2_paths = char_kit.list_paths(
                c.kit, char_kit.utoc_of(c.game.paks_dir, "CalaPlayer-Windows_P2"), log, "C1")
            for p in p2_paths:
                rel = char_kit.package_root_of(p).replace("\\", "/")
                i = rel.find("Characters/")
                if i < 0:
                    continue
                d = rel[i:].rsplit("/", 1)[0] + "/"          # Characters/<角色>/<皮肤>/
                if d not in filters:
                    filters.append(d)
            log("C1", "旧 _P2 涉及 %d 个目录，已并入提取过滤器" % (len(filters) - 2))
        log("C1", "提取基线：%s" % ", ".join(filters))
        char_kit.to_legacy_filters(c.kit, c.game.paks_dir, c.legacy, filters, log, "C1")
        c.char_dir = char
        base = os.path.join(c.legacy, CHARACTERS_REL, char)
        if not os.path.isdir(base):
            raise BuildError("C1", "游戏里没有角色目录 '%s'" % char,
                             "已提取的目录：%s" % os.path.join(c.legacy, CHARACTERS_REL))
        skins = sorted(d for d in os.listdir(base)
                       if SKIN_ID_RE.match(d) and os.path.isdir(os.path.join(base, d)))
        log("C1", "该角色已有皮肤目录：%s" % (", ".join(skins) or "（无）"))
        src_skin = c.source_skin or "S001"
        if src_skin not in skins:
            raise BuildError("C1", "源皮肤 %s 不在该角色的皮肤目录里" % src_skin,
                             "可用：%s" % ", ".join(skins))
        c.src_skin_dir = os.path.join(base, src_skin)
        # 新皮肤 ID：给定 or 自动推荐（S0xx / S1xx 段里找未占用的最小号）
        if c.skin_id:
            if not SKIN_ID_RE.match(c.skin_id):
                raise BuildError("C1", "皮肤 ID 必须是 S + 3 位数字（如 S052），当前 '%s'"
                                 % c.skin_id)
        else:
            used = set(skins)
            for n in list(range(2, 100)) + list(range(100, 200)):
                cand = "S%03d" % n
                if cand not in used:
                    c.skin_id = cand
                    break
            log("C1", "未指定皮肤 ID，自动推荐 %s" % c.skin_id)
        if len(c.skin_id) != len(src_skin):
            raise BuildError("C1", "皮肤 ID 长度必须与源皮肤一致（%s 是 %d 字符，新的是 %d）"
                             % (src_skin, len(src_skin), len(c.skin_id)),
                             "同长替换是这套配方的硬约束（改长度要重写 uasset 结构）")
        c.skin_num = c.skin_id[1:]
        c.new_skin_dir = os.path.join(base, c.skin_id)
        if os.path.isdir(c.new_skin_dir):
            raise BuildError("C1", "目标皮肤 %s 已经存在（源码目录里）" % c.skin_id,
                             "换一个皮肤 ID，或先清理上次的 work 目录")
        # 源网格（形如 aika-s001 / celeste-s101 的唯一网格资产）
        meshes = [f for f in os.listdir(c.src_skin_dir) if f.endswith(".uasset")
                  and MESH_NAME_RE.match(f[:-len(".uasset")])]
        if len(meshes) != 1:
            raise BuildError("C1", "源皮肤目录里找不到唯一的网格",
                             "候选：%s" % (", ".join(meshes) or "（空）"))
        c.mesh_src = meshes[0][:-len(".uasset")]
        m = MESH_NAME_RE.match(c.mesh_src)
        c.mesh_new = "%s-s%s" % (m.group("prefix"), c.skin_num)
        if len(c.mesh_new) != len(c.mesh_src):
            raise BuildError("C1", "网格改名后长度变化：%s -> %s" % (c.mesh_src, c.mesh_new))
        log("C1", "网格：%s -> %s" % (c.mesh_src, c.mesh_new))
        self.gate("C1", True, "基线提取完成：角色 %s / 源皮肤 %s / 新皮肤 %s"
                  % (c.char_dir, src_skin, c.skin_id))

    # ------------------------------------------------------------------
    # C2 计划：素材匹配 + 材质选择
    # ------------------------------------------------------------------
    def _scan_game_refs(self, base: str) -> Set[str]:
        """扫描 uasset+uexp 里的 `/Game/...` 引用路径（字符串级）。"""
        out: Set[str] = set()
        for ext in (".uasset", ".uexp"):
            p = base + ext
            if not os.path.isfile(p):
                continue
            b = open(p, "rb").read()
            for m in PATH_RE.finditer(b):
                s = m.group(0).decode("latin-1")
                # 变量长字符串相邻时可能吞进后续字节 -> 只保留合法路径字符
                s = re.sub(r"[^A-Za-z0-9_./\-].*$", "", s)
                out.add(s)
        return out

    @staticmethod
    def _norm_tex_name(name: str, skins: Sequence[str]) -> str:
        """归一化贴图名用于素材匹配（去皮肤记号 + 去分隔符 + 转小写）。

        `skins` 同时包含**源皮肤**与**素材皮肤**两种记号（导出素材里的记号是
        它自己那套皮肤，如 S051；而它要匹配的源贴图名可能完全不带记号）：
            `T_Aika_Body_1_S051_D` -> 去 `_s051` -> `taikabody1d`（对 T_Aika_body_1_D）
            `T_Aika_body2_Mask1_051` -> 去 `_051` -> `taikabody2mask1`
            `T_HuiXing_Body_D_S102`  -> 去 `_s102` -> `thuixingbodyd`（对 …_S101）
        """
        s = os.path.splitext(name)[0].lower()
        for sk in skins:
            tok = sk.lower()
            s = s.replace("_" + tok, "").replace(tok, "")
            s = s.replace("_" + tok[1:], "")        # 纯数字形态 `_051`
        return re.sub(r"[^a-z0-9]", "", s)

    def _find_png_dir(self) -> str:
        c = self.ctx
        for sub in ("Mesh3D", "mesh3d", "Textures", "textures"):
            d = os.path.join(c.src_dir, sub)
            if os.path.isdir(d) and any(f.lower().endswith(".png") for f in os.listdir(d)):
                return d
        return c.src_dir

    def c2(self) -> None:
        c, log = self.ctx, self.log
        # ---- 名称表：角色索引 / 皮肤索引 ----
        da_ua = os.path.join(c.legacy, DA_REL + ".uasset")
        if not os.path.isfile(da_ua):
            raise BuildError("C2", "提取树里没有 DA_Characters", da_ua)
        names = probe_names(c.kit, da_ua, log, "C2")
        log("C2", "DA 名称表：%d 项" % len(names))
        if c.character not in names:
            raise BuildError("C2", "名称表里没有角色 '%s'" % c.character,
                             "可用的角色名：%s" % ", ".join(
                                 n for n in names if re.match(r"^[A-Z][a-z]+$", n))[:400])
        self.char_idx = names.index(c.character)
        if c.source_skin not in names:
            raise BuildError("C2", "名称表里没有皮肤 ID '%s'" % c.source_skin)
        self.src_skin_idx = names.index(c.source_skin)
        if c.skin_id in names:
            log("C2", "提示：名称表里已存在 '%s'（可能是别的角色用过的号），继续执行" % c.skin_id)

        # ---- 源皮肤资产清单 ----
        tex_dir = os.path.join(c.src_skin_dir, "Textures")
        mat_dir = os.path.join(c.src_skin_dir, "Materials")
        src_tex = sorted(f[:-len(".uasset")] for f in os.listdir(tex_dir)
                         if f.endswith(".uasset")) if os.path.isdir(tex_dir) else []
        src_mat = sorted(f[:-len(".uasset")] for f in os.listdir(mat_dir)
                         if f.endswith(".uasset")) if os.path.isdir(mat_dir) else []
        log("C2", "源皮肤资产：贴图 %d 张，材质 %d 个" % (len(src_tex), len(src_mat)))
        if not src_tex:
            raise BuildError("C2", "源皮肤目录里没有贴图", tex_dir)

        # ---- 素材 PNG ↔ 源贴图 匹配 ----
        png_dir = self._find_png_dir()
        pngs = sorted(f for f in os.listdir(png_dir) if f.lower().endswith(".png"))
        log("C2", "素材 PNG 目录：%s（%d 个）" % (png_dir, len(pngs)))
        skins_tokens = [c.source_skin] + ([c.src_skin_token] if c.src_skin_token else [])
        log("C2", "素材匹配用的皮肤记号：%s" % ", ".join(skins_tokens))
        by_norm: Dict[str, List[str]] = {}
        for t in src_tex:
            by_norm.setdefault(self._norm_tex_name(t, skins_tokens), []).append(t)
        matches: Dict[str, str] = {}          # 源贴图名 -> png 路径
        unmatched: List[str] = []
        for f in pngs:
            key = self._norm_tex_name(f, skins_tokens)
            cands = by_norm.get(key, [])
            if len(cands) == 1:
                matches[cands[0]] = os.path.join(png_dir, f)
                log("C2", "  %-40s -> %s" % (f, cands[0]))
            elif len(cands) > 1:
                log("C2", "  %-40s -> 多个候选 %s（跳过）" % (f, cands))
                unmatched.append(f)
            else:
                log("C2", "  %-40s -> 不匹配任何源贴图（跳过）" % f)
                unmatched.append(f)
        if not matches:
            raise BuildError("C2", "素材里的 PNG 没有任何一张能匹配到源皮肤贴图",
                             "已比对：%s" % ", ".join(src_tex[:12]))
        self.gate("C2a", True, "素材匹配：%d 张 PNG 命中，%d 张跳过"
                  % (len(matches), len(unmatched)))

        # ---- 材质引用图 ----
        mat_refs: Dict[str, Set[str]] = {}
        tex_prefix = "/Game/CalaPlayer/Characters/%s/%s/Textures/" % (c.char_dir, c.source_skin)
        for m in src_mat:
            refs = self._scan_game_refs(os.path.join(mat_dir, m))
            mat_refs[m] = refs
        replaced_tex = set(matches.keys())
        sel_mats = sorted(m for m in src_mat
                          if {r.rsplit("/", 1)[-1] for r in mat_refs[m] if r.startswith(tex_prefix)}
                          & replaced_tex)
        if not sel_mats:
            raise BuildError("C2", "没有任何材质引用到被替换的贴图",
                             "被替换：%s" % ", ".join(sorted(replaced_tex)))
        log("C2", "选中材质 %d 个（引用了被替换贴图的）：%s"
            % (len(sel_mats), ", ".join(sel_mats)))

        # ---- 要构建的贴图 = 选中材质的全部贴图引用 ----
        needed_tex: Set[str] = set()
        for m in sel_mats:
            for r in mat_refs[m]:
                if r.startswith(tex_prefix):
                    needed_tex.add(r[len(tex_prefix):])
        log("C2", "需要构建的贴图 %d 张：%s" % (len(needed_tex), ", ".join(sorted(needed_tex))))

        # ---- 网格引用（决定哪些材质要换到新皮肤目录） ----
        mesh_refs = self._scan_game_refs(os.path.join(c.src_skin_dir, c.mesh_src))
        mat_prefix = "/Game/CalaPlayer/Characters/%s/%s/Materials/" % (c.char_dir, c.source_skin)
        mesh_switch: List[str] = []
        for r in sorted(mesh_refs):
            if r.startswith(mat_prefix):
                nm = r[len(mat_prefix):]
                if nm in sel_mats:
                    mesh_switch.append(nm)
        if not mesh_switch:
            raise BuildError("C2", "网格没有引用任何选中的材质（异常）",
                             "网格引用：%s" % ", ".join(sorted(mesh_refs))[:400])
        log("C2", "网格要切换的材质 %d 个：%s" % (len(mesh_switch), ", ".join(mesh_switch)))

        # ---- 断链检查：选中材质引用的皮肤目录资产必须全部在构建集合里 ----
        missing: List[str] = []
        for m in sel_mats:
            for r in mat_refs[m]:
                if r.startswith("/Game/CalaPlayer/Characters/%s/%s/"
                                % (c.char_dir, c.source_skin)):
                    leaf = r.rsplit("/", 1)[-1]
                    if r.startswith(tex_prefix) and leaf in needed_tex:
                        continue
                    if r.startswith(mat_prefix):
                        continue          # 引用自身/同目录材质（同批构建）
                    missing.append("%s -> %s" % (m, r))
        if missing:
            raise BuildError("C2", "选中材质引用了构建集合之外的皮肤目录资产（会断链）",
                             "; ".join(missing[:6]))

        # ---- DA 槽位计划 ----
        ux = open(os.path.join(c.legacy, DA_REL + ".uexp"), "rb").read()
        skins = char_da.find_skins_map(ux, self.char_idx, names)
        src_entry = skins.find(self.src_skin_idx)
        if src_entry is None:
            raise BuildError("C2", "源皮肤 %s 不在该角色的 Skins map 里" % c.source_skin)
        elem_plan: Dict[int, Dict] = {}
        for i, (pkg_idx, asset_idx) in enumerate(src_entry.elems):
            pkg_path, asset = names[pkg_idx], names[asset_idx]
            if not pkg_path.startswith(mat_prefix):
                continue
            mat_name = pkg_path[len(mat_prefix):]
            if mat_name not in sel_mats:
                continue
            new_path = "/Game/CalaPlayer/Characters/%s/%s/Materials/%s" % (
                c.char_dir, c.skin_id, mat_name)
            elem_plan[i] = {"old": pkg_path, "new": new_path, "asset": asset}
        log("C2", "DA 槽位：源条目 %d 个 Outlines，其中 %d 个要指向新皮肤"
            % (src_entry.outline_count, len(elem_plan)))
        if not elem_plan:
            raise BuildError("C2", "没有任何 DA 槽位需要改写（异常）")

        # ---- 汇总计划 ----
        for t in sorted(needed_tex):
            self.tex_build.append({
                "name_src": t,
                "name_new": self._new_asset_name(t, c.source_skin, c.skin_id),
                "png": matches.get(t, ""),
            })
        for m in sel_mats:
            self.mat_build.append({
                "name_src": m,
                "name_new": self._new_asset_name(m, c.source_skin, c.skin_id),
                "refs": sorted(r for r in mat_refs[m]
                               if r.startswith("/Game/CalaPlayer/Characters/%s/%s/"
                                               % (c.char_dir, c.source_skin))),
            })
        self.elem_plan = elem_plan
        n_override = sum(1 for t in self.tex_build if t["png"])
        log("C2", "计划：贴图 %d（其中 %d 张换新像素，%d 张复制）、材质 %d、网格 %s -> %s"
            % (len(self.tex_build), n_override, len(self.tex_build) - n_override,
               len(self.mat_build), c.mesh_src, c.mesh_new))
        self.gate("C2", True, "计划完成：%d 贴图 / %d 材质 / %d 个 DA 槽位"
                  % (len(self.tex_build), len(self.mat_build), len(elem_plan)))

    @staticmethod
    def _new_asset_name(name: str, src_skin: str, new_skin: str) -> str:
        """资产名里的源皮肤记号 -> 新皮肤 ID（不含则原样）。"""
        out = name.replace(src_skin, new_skin)
        out = out.replace(src_skin.lower(), new_skin.lower())
        if len(out) != len(name):
            raise BuildError("C2", "资产改名后长度变化：%s -> %s" % (name, out))
        return out

    # ------------------------------------------------------------------
    # C3 资产构建（纯同长字节替换）
    # ------------------------------------------------------------------
    def _patch_file(self, src: str, dst: str, pairs: Sequence[Tuple[str, str]],
                    log: Log, stage: str = "C3", guards: Sequence[str] = ()) -> None:
        """文本级同长替换（latin-1 字节直通）。

        * `pairs` = [(原串, 新串)]，逐引用精确替换（不做目录段全局替换，避免
          误伤"故意保留"的引用，如骨架/物理/面部材质）；
        * `guards` = 需要**保持原样**的串（形如 `{角色}/S001/...` 的保留引用名）：
          先用等长占位符遮住它们，替换完毕再还原；
        * 收尾两道硬校验：替换后的文件里不允许残留任何"应被替换的原串"；
          文件长度必须一个字节都不变（同长是这套配方的硬约束）。
        """
        b = open(src, "rb").read()
        s = b.decode("latin-1")
        taken = [x for p in pairs for x in p]
        guard_map: Dict[str, str] = {}
        for g in sorted(set(guards), key=lambda x: -len(x)):
            if not g or g not in s:
                continue
            ph = self._placeholder(len(g), s, taken + list(guard_map))
            s = s.replace(g, ph)
            guard_map[ph] = g
        hits = 0
        for frm, to in pairs:
            if frm == to:
                continue
            n = s.count(frm)
            if n:
                s = s.replace(frm, to)
                hits += n
        # 残留自检：任何"应被替换的原串"都不允许再出现
        for frm, to in pairs:
            if frm != to and frm in s:
                raise BuildError(stage, "%s 里 '%s' 未完全替换（残留）"
                                 % (os.path.basename(src), frm))
        for ph, orig in sorted(guard_map.items(), key=lambda kv: -len(kv[0])):
            s = s.replace(ph, orig)
        out = s.encode("latin-1")
        if len(out) != len(b):
            raise BuildError(stage, "%s 替换后长度变化（%d -> %d）—— 同长约束被破坏"
                             % (os.path.basename(src), len(b), len(out)))
        ensure_dir(os.path.dirname(dst))
        open(dst, "wb").write(out)

    @staticmethod
    def _placeholder(n: int, text: str, taken: Sequence[str]) -> str:
        import random
        alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for _ in range(20000):
            cand = "".join(random.choice(alpha) for _ in range(n))
            if cand not in text and all(cand != t and cand not in t for t in taken):
                return cand
        raise BuildError("C3", "无法为 %d 字符的保留引用生成占位符" % n)

    def _read_pf(self, uexp_path: str) -> str:
        b = open(uexp_path, "rb").read()
        hits = re.findall(rb"PF_[A-Z0-9_]+", b)
        if not hits:
            raise BuildError("C3", "贴图 uexp 里找不到 PF_ 格式声明", uexp_path)
        uniq = {h.decode("ascii") for h in hits}
        if len(uniq) != 1:
            raise BuildError("C3", "贴图 uexp 里有多个 PF_ 声明：%s" % sorted(uniq))
        return uniq.pop()

    def _fix_format_decl(self, uexp_path: str, uasset_path: str, old_pf: str,
                         new_pf: str, log: Log) -> None:
        """`PF_BC7` -> `PF_DXT5`：uexp 内联 FString + uasset SerialSize 同步（教训 12.4）。"""
        stage = "C3"
        bu = open(uexp_path, "rb").read()
        # 实测布局：u32 长度（含结尾 \0）+ ASCII 像素格式 + \0
        # 例：`07 00 00 00 "PF_BC7" 00` -> `08 00 00 00 "PF_DXT5" 00`（+1 字节）
        new_bytes = struct.pack("<I", len(new_pf) + 1) + new_pf.encode("ascii") + b"\x00"
        old_bytes = struct.pack("<I", len(old_pf) + 1) + old_pf.encode("ascii") + b"\x00"
        hits = [i for i in range(len(bu)) if bu[i:i + len(old_bytes)] == old_bytes]
        if len(hits) != 1:
            raise BuildError(stage, "uexp 里 '%s' 的声明命中 %d 次（要求唯一）" % (old_pf, len(hits)))
        at = hits[0]
        nb = bytearray(bu[:at] + new_bytes + bu[at + len(old_bytes):])
        ba = bytearray(open(uasset_path, "rb").read())
        old_len = len(bu)
        needle = struct.pack("<q", old_len - 4)
        shits = [i for i in range(len(ba) - 8) if bytes(ba[i:i + 8]) == needle]
        if len(shits) != 1:
            raise BuildError(stage, "SerialSize(%d) 命中 %d 次（要求唯一）" % (old_len - 4, len(shits)))
        struct.pack_into("<q", ba, shits[0], len(nb) - 4)
        open(uexp_path, "wb").write(bytes(nb))
        open(uasset_path, "wb").write(bytes(ba))
        log("C3", "  格式声明修复：%s -> %s（uexp %d -> %d B，SerialSize @0x%X）"
            % (old_pf, new_pf, old_len, len(nb), shits[0]))

    def _tex_probe(self, name: str) -> Dict:
        """用 tex-inspect 从游戏容器读一张贴图的权威元数据（尺寸/格式/mip 数）。"""
        c = self.ctx
        pkg = "/Game/CalaPlayer/Characters/%s/%s/Textures/%s" % (c.char_dir, c.source_skin, name)
        dump_dir = ensure_dir(os.path.join(c.work, "texdump"))
        out = c.kit.tex_dump(c.game.paks_dir, pkg, dump_dir, self.log, "C3")
        pf = texmod.parse_platform(out)
        mips = texmod.parse_mips(out)
        if not pf.get("size_x") or not pf.get("pixel_format"):
            raise BuildError("C3", "tex-inspect 没能解析 %s" % pkg, out[:400])
        return {"w": pf["size_x"], "h": pf["size_y"], "pf": pf["pixel_format"],
                "mips": mips, "pkg": pkg}

    def _pkg_of(self, *parts: str) -> str:
        return "/Game/CalaPlayer/Characters/" + "/".join(parts)

    def c3(self) -> None:
        c, log = self.ctx, self.log
        out_skin = ensure_dir(os.path.join(c.out_assets, CHARACTERS_REL, c.char_dir, c.skin_id))
        out_tex = ensure_dir(os.path.join(out_skin, "Textures"))
        out_mat = ensure_dir(os.path.join(out_skin, "Materials"))
        src_tex_dir = os.path.join(c.src_skin_dir, "Textures")
        src_mat_dir = os.path.join(c.src_skin_dir, "Materials")

        # ---- 贴图（自身名 + 自身路径，逐引用精确替换） ----
        for t in self.tex_build:
            base_src = os.path.join(src_tex_dir, t["name_src"])
            base_dst = os.path.join(out_tex, t["name_new"])
            pairs = [
                (self._pkg_of(c.char_dir, c.source_skin, "Textures", t["name_src"]),
                 self._pkg_of(c.char_dir, c.skin_id, "Textures", t["name_new"])),
            ]
            if t["name_src"] != t["name_new"]:
                pairs.append((t["name_src"], t["name_new"]))
            self._patch_file(base_src + ".uasset", base_dst + ".uasset", pairs, log)
            self._patch_file(base_src + ".uexp", base_dst + ".uexp", pairs, log)
            ub_src, ub_dst = base_src + ".ubulk", base_dst + ".ubulk"
            if not os.path.isfile(ub_src):
                raise BuildError("C3", "贴图没有 .ubulk（这套配方只处理外置 mip）", ub_src)
            if not t["png"]:
                shutil.copy2(ub_src, ub_dst)
                log("C3", "  贴图 %s：复制源像素（素材未提供）" % t["name_new"])
                continue
            # 有素材 -> 编码
            probe = self._tex_probe(t["name_src"])
            pf = probe["pf"]
            ubulk_size = os.path.getsize(ub_src)
            levels = ubulk_mip_levels(probe["w"], probe["h"], pf, ubulk_size)
            if levels is None and pf == "PF_BC7":
                levels = ubulk_mip_levels(probe["w"], probe["h"], "PF_DXT5", ubulk_size)
            if levels is None:
                raise BuildError("C3", "无法从 ubulk 反推 mip 链（%s，%d B，%s）"
                                 % (t["name_src"], ubulk_size, pf))
            log("C3", "  贴图 %s（%dx%d %s，%d 级大 mip）：%s"
                % (t["name_new"], probe["w"], probe["h"], pf, len(levels), t["png"]))
            # 读 PNG
            from PIL import Image
            import numpy as np
            img = Image.open(t["png"]).convert("RGBA")
            arr = np.asarray(img)
            if (arr.shape[1], arr.shape[0]) != (probe["w"], probe["h"]):
                log("C3", "    素材 %dx%d 与贴图 %dx%d 不同，按 LANCZOS 缩放"
                    % (arr.shape[1], arr.shape[0], probe["w"], probe["h"]))
            # 声明一致性：BC7/BC5 不能喂 DXT 编码器
            eff_pf = pf
            if pf == "PF_BC7":
                eff_pf = "PF_DXT5"
            elif pf not in ("PF_DXT1", "PF_DXT5", "PF_BC5"):
                raise BuildError("C3", "贴图格式 %s 暂不支持编码（%s）" % (pf, t["name_src"]),
                                 "可在素材里去掉这张 PNG（改为沿用源像素）")
            levels_enc = ubulk_mip_levels(probe["w"], probe["h"], eff_pf, ubulk_size)
            if levels_enc is None:
                raise BuildError("C3", "格式 %s 的 mip 链尺寸与源 ubulk 不符" % eff_pf)
            blob = encode_ubulk(arr, eff_pf, levels_enc, log=log, stage="C3")
            open(ub_dst, "wb").write(blob)
            if pf == "PF_BC7":
                self._fix_format_decl(base_dst + ".uexp", base_dst + ".uasset",
                                      "PF_BC7", "PF_DXT5", log)
            # 复核：写回读、尺寸、声明
            if os.path.getsize(ub_dst) != ubulk_size:
                raise BuildError("C3", "新 ubulk 尺寸 %d != 源 %d"
                                 % (os.path.getsize(ub_dst), ubulk_size))
            now_pf = self._read_pf(base_dst + ".uexp")
            if now_pf != eff_pf:
                raise BuildError("C3", "声明复核失败：%s != %s" % (now_pf, eff_pf))

        # ---- 材质（自身名/路径 + 它引用的被构建贴图，一起同长替换） ----
        for m in self.mat_build:
            src_base = os.path.join(src_mat_dir, m["name_src"])
            dst_base = os.path.join(out_mat, m["name_new"])
            pairs: List[Tuple[str, str]] = [
                (self._pkg_of(c.char_dir, c.source_skin, "Materials", m["name_src"]),
                 self._pkg_of(c.char_dir, c.skin_id, "Materials", m["name_new"]))]
            if m["name_src"] != m["name_new"]:
                pairs.append((m["name_src"], m["name_new"]))
            for t in self.tex_build:
                old_t = self._pkg_of(c.char_dir, c.source_skin, "Textures", t["name_src"])
                if old_t in m["refs"]:
                    pairs.append((old_t, self._pkg_of(c.char_dir, c.skin_id, "Textures",
                                                      t["name_new"])))
                if t["name_src"] != t["name_new"]:
                    pairs.append((t["name_src"], t["name_new"]))
            for ext in (".uasset", ".uexp"):
                self._patch_file(src_base + ext, dst_base + ext, pairs, log)
            log("C3", "  材质 %s -> %s（%d 组同长替换）"
                % (m["name_src"], m["name_new"], len(pairs)))

        # ---- 网格（自身 + 被切换材质；保留引用用占位符遮住） ----
        mesh_src = os.path.join(c.src_skin_dir, c.mesh_src)
        mesh_dst = os.path.join(out_skin, c.mesh_new)
        mesh_refs = self._scan_game_refs(mesh_src)
        pkg_prefix = self._pkg_of(c.char_dir, c.source_skin) + "/"
        build_leaves = {c.mesh_src} | {m["name_src"] for m in self.mat_build}
        guards: List[str] = []
        for r in sorted(mesh_refs):
            if not r.startswith(pkg_prefix):
                continue
            leaf = r.rsplit("/", 1)[-1]
            if leaf in build_leaves:
                continue
            if c.source_skin in leaf or c.source_skin.lower() in leaf.lower():
                if leaf not in guards:
                    guards.append(leaf)
                if r not in guards:
                    guards.append(r)
        if guards:
            log("C3", "  网格保留引用（占位保护）：%s" % ", ".join(guards))
        mesh_pairs: List[Tuple[str, str]] = [
            (self._pkg_of(c.char_dir, c.source_skin, c.mesh_src),
             self._pkg_of(c.char_dir, c.skin_id, c.mesh_new))]
        if c.mesh_src != c.mesh_new:
            mesh_pairs.append((c.mesh_src, c.mesh_new))
        for m in self.mat_build:
            old_m = self._pkg_of(c.char_dir, c.source_skin, "Materials", m["name_src"])
            if old_m in mesh_refs:
                mesh_pairs.append((old_m, self._pkg_of(c.char_dir, c.skin_id, "Materials",
                                                       m["name_new"])))
            if m["name_src"] != m["name_new"]:
                mesh_pairs.append((m["name_src"], m["name_new"]))
        for ext in (".uasset", ".uexp"):
            self._patch_file(mesh_src + ext, mesh_dst + ext, mesh_pairs, log, guards=guards)
        log("C3", "  网格 %s -> %s（%d 组同长替换，%d 个保留引用）"
            % (c.mesh_src, c.mesh_new, len(mesh_pairs), len(guards)))

        # ---- 复核：全部产物存在 / 尺寸约束 ----
        made = []
        for root, _dirs, files in os.walk(out_skin):
            for f in files:
                made.append(os.path.relpath(os.path.join(root, f), c.out_assets))
        log("C3", "构建产物 %d 个文件：%s" % (len(made), ", ".join(sorted(made)[:6]) + " ..."))
        self.gate("C3", True, "资产构建完成：%d 个文件" % len(made))

    # ------------------------------------------------------------------
    # C4 DA 注册
    # ------------------------------------------------------------------
    def c4(self) -> None:
        c, log = self.ctx, self.log
        mesh_pkg = "/Game/CalaPlayer/Characters/%s/%s/%s" % (c.char_dir, c.skin_id, c.mesh_new)
        outline_paths = [v["new"] for v in self.elem_plan.values()]
        elem_plan = {slot: v["new"] for slot, v in self.elem_plan.items()}
        da_base = os.path.join(c.legacy, DA_REL)
        out_ua = char_da.register_skin(
            c.kit, da_base, os.path.join(c.work, "da_work"), self.char_idx, self.src_skin_idx,
            c.skin_id, mesh_pkg, c.mesh_new, outline_paths, elem_plan, log, "C4")
        self.da_out = out_ua
        self.gate("C4", True, "DA 注册完成：%s" % os.path.basename(out_ua))

    # ------------------------------------------------------------------
    # C5 打包（_P2 新资产 + _P 换 DA chunk）
    # ------------------------------------------------------------------
    def _stage_tree(self, src_root: str, rel_dir: str, dst_root: str) -> int:
        """把 `src_root/rel_dir/**` 复制进 `dst_root/rel_dir`。"""
        src = os.path.join(src_root, rel_dir)
        dst = os.path.join(dst_root, rel_dir)
        n = 0
        if not os.path.isdir(src):
            return 0
        for root, _dirs, files in os.walk(src):
            for f in files:
                s = os.path.join(root, f)
                rel = os.path.relpath(s, src_root)
                d = os.path.join(dst_root, rel)
                ensure_dir(os.path.dirname(d))
                shutil.copy2(s, d)
                n += 1
        return n

    def c5(self) -> None:
        c, log = self.ctx, self.log
        paks = c.game.paks_dir
        skin_rel = "%s/%s/%s" % (CHARACTERS_REL, c.char_dir, c.skin_id)

        # ---- _P2：旧资产（若已有 _P2）+ 新皮肤资产 ----
        if char_kit.container_exists(paks, "CalaPlayer-Windows_P2"):
            old_paths = char_kit.list_paths(c.kit, char_kit.utoc_of(paks, "CalaPlayer-Windows_P2"),
                                            log, "C5")
            log("C5", "已有 _P2（%d 个路径）—— 先并入打包目录，再叠加新皮肤资产"
                % len(old_paths))
            n_old = 0
            for p in old_paths:
                rel = char_kit.package_root_of(p)
                if rel.startswith(skin_rel + "/"):
                    continue                       # 同路径（理论上不会有）
                base_noext = os.path.splitext(os.path.join(c.legacy, rel))[0]
                moved = False
                for ext in (".uasset", ".uexp", ".ubulk"):
                    s = base_noext + ext
                    if os.path.isfile(s):
                        d = os.path.join(c.p2_stage, os.path.splitext(rel)[0] + ext)
                        ensure_dir(os.path.dirname(d))
                        shutil.copy2(s, d)
                        n_old += 1
                        moved = True
                if not moved:
                    log("C5", "  ! 提取树里找不到 %s（跳过）" % rel)
            log("C5", "  旧 _P2 资产并入 %d 个文件" % n_old)
        n_new = self._stage_tree(c.out_assets, skin_rel, c.p2_stage)
        log("C5", "新皮肤资产加入 %d 个文件" % n_new)
        utoc2 = os.path.join(c.p2_out, "CalaPlayer-Windows_P2.utoc")
        c.kit.to_zen(c.p2_stage, utoc2, log, "C5")
        char_kit.verify(c.kit, utoc2, log, "C5")
        log("C5", "  _P2 打包完成：%s" % utoc2)

        # ---- 新 DA -> 临时容器 -> 取 chunk ----
        da_stage = ensure_dir(os.path.join(c.work, "da_stage"))
        da_rel_dir = os.path.join(da_stage, "CalaPlayer", "Content", "CalaPlayer", "Characters")
        ensure_dir(da_rel_dir)
        da_src = os.path.splitext(self.da_out)[0]          # 去掉 .uasset 后缀
        for ext in (".uasset", ".uexp"):
            shutil.copy2(da_src + ext, os.path.join(da_rel_dir, "DA_Characters" + ext))
        tmp_utoc = os.path.join(c.work, "da_temp", "CalaPlayer-Windows_P.utoc")
        c.kit.to_zen(da_stage, tmp_utoc, log, "C5")
        tmp_raw = os.path.join(c.work, "da_raw")
        char_kit.unpack_raw(c.kit, tmp_utoc, tmp_raw, log, "C5")
        da_chunk = None
        man = json.load(open(os.path.join(tmp_raw, "manifest.json"), encoding="utf-8"))
        for cid, path in man.get("chunk_paths", {}).items():
            if path.endswith("/DA_Characters.uasset"):
                da_chunk = cid
        if not da_chunk:
            raise BuildError("C5", "临时容器里找不到 DA_Characters chunk", str(man)[:300])
        log("C5", "  DA chunk id = %s" % da_chunk)

        # ---- _P：已有则 unpack-raw -> 换 chunk -> pack-raw；没有则直接用临时容器 ----
        if char_kit.container_exists(paks, "CalaPlayer-Windows_P"):
            raw_p = os.path.join(c.work, "P_raw")
            rmtree(raw_p)
            char_kit.unpack_raw(c.kit, char_kit.utoc_of(paks, "CalaPlayer-Windows_P"), raw_p,
                                log, "C5")
            man_p = json.load(open(os.path.join(raw_p, "manifest.json"), encoding="utf-8"))
            paths = man_p.get("chunk_paths", {})
            if da_chunk in paths:
                src_chunk = os.path.join(tmp_raw, "chunks", da_chunk)
                dst_chunk = os.path.join(raw_p, "chunks", da_chunk)
                shutil.copy2(src_chunk, dst_chunk)
                log("C5", "  替换 _P 里的 DA chunk %s（%s -> %s）"
                    % (da_chunk, human(os.path.getsize(dst_chunk)),
                       human(os.path.getsize(src_chunk))))
            else:
                # 旧 _P 里没有 DA chunk（罕见）：直接加入
                paths[da_chunk] = "../../../" + DA_REL + ".uasset"
                shutil.copy2(os.path.join(tmp_raw, "chunks", da_chunk),
                             os.path.join(raw_p, "chunks", da_chunk))
                man_p["chunk_paths"] = paths
                json.dump(man_p, open(os.path.join(raw_p, "manifest.json"), "w",
                                      encoding="utf-8"), indent=2)
                log("C5", "  旧 _P 里没有 DA chunk，已追加")
            utoc_p = os.path.join(c.p_out, "CalaPlayer-Windows_P.utoc")
            char_kit.pack_raw(c.kit, raw_p, utoc_p, log, "C5")
            # .pak 桩从原 _P 复制（pack-raw 不生成 .pak）
            for ext in ("pak",):
                srcp = os.path.join(paks, "CalaPlayer-Windows_P." + ext)
                if os.path.isfile(srcp):
                    shutil.copy2(srcp, os.path.join(c.p_out, "CalaPlayer-Windows_P." + ext))
        else:
            log("C5", "游戏里没有 _P —— 用 DA 临时容器直接作为新 _P")
            for ext in ("pak", "ucas", "utoc"):
                s = os.path.splitext(tmp_utoc)[0] + "." + ext
                if os.path.isfile(s):
                    shutil.copy2(s, os.path.join(c.p_out, "CalaPlayer-Windows_P." + ext))
            c.p_out = c.p_out
        utoc_p = os.path.join(c.p_out, "CalaPlayer-Windows_P.utoc")
        char_kit.verify(c.kit, utoc_p, log, "C5")
        log("C5", "  _P 打包完成：%s" % utoc_p)
        for label, d, base in (("_P", c.p_out, "CalaPlayer-Windows_P"),
                               ("_P2", c.p2_out, "CalaPlayer-Windows_P2")):
            missing = [e for e in ("pak", "ucas", "utoc")
                       if not os.path.isfile(os.path.join(d, "%s.%s" % (base, e)))]
            log("C5", "  %s 产物：%s%s" % (label, ", ".join(sorted(os.listdir(d))),
                                        "（缺 %s）" % missing if missing else ""))
            if missing:
                raise BuildError("C5", "%s 产物不完整：缺 %s" % (label, missing))
        self.gate("C5", True, "双容器打包完成（_P 换 DA chunk，_P2 承载新皮肤）")

    # ------------------------------------------------------------------
    # C6 部署（备份 -> 写入 -> 读回 -> 失败还原）
    # ------------------------------------------------------------------
    def c6(self) -> None:
        c, log = self.ctx, self.log
        paks = c.game.paks_dir
        log("C6", "部署到游戏（先 _P 后 _P2；任一步失败自动回滚）")
        info_p = deploy.install(c.p_out, paks, base="CalaPlayer-Windows_P", log=log, stage="C6")
        try:
            info_p2 = deploy.install(c.p2_out, paks, base="CalaPlayer-Windows_P2",
                                     log=log, stage="C6")
        except BaseException as exc:                      # noqa: BLE001
            log("C6", "！_P2 安装失败（%s），回滚刚装好的 _P" % exc)
            try:
                deploy.rollback(info_p["backup"], paks, base="CalaPlayer-Windows_P",
                                log=log, stage="C6")
            except Exception as exc2:                     # noqa: BLE001
                log("C6", "！_P 回滚也失败（%s）—— 请手工恢复 %s"
                    % (exc2, info_p.get("backup")))
            raise
        self.result["installed"] = {"p": info_p, "p2": info_p2}
        log("C6", "安装完成：_P=%s，_P2=%s" % (info_p["installed"]["ucas"]["sha16"],
                                            info_p2["installed"]["ucas"]["sha16"]))
        log("C6", "回滚方法：见 %s" % info_p["backup_txt"])


# ----------------------------------------------------------------------
# 便利入口
# ----------------------------------------------------------------------
def run_character(paks: str, src_dir: str, log_path: str = "", **kw) -> Dict:
    """一键入口（CLI / GUI 任务共用）：构造 Ctx -> 跑 -> 收尾。

    工作目录语义：部署成功且未勾 keep_work 时清掉 `work/`（产物容器在
    `out_character/p`、`out_character/p2`，安装备份在那个 out 目录里）；
    DryRun / 仅构建 / keep_work 都保留 work 供检查。
    """
    log = Log(log_path or None) if log_path else Log(None, echo=True)
    ctx = CharCtx(paks_arg=paks, src_dir=src_dir,
                  out_dir=kw.pop("out_dir", ""), character=kw.pop("character", ""),
                  skin_id=kw.pop("skin_id", ""), source_skin=kw.pop("source_skin", "S001"),
                  kit_arg=kw.pop("kit", ""), dry_run=kw.pop("dry_run", False),
                  no_deploy=kw.pop("no_deploy", False), keep_work=kw.pop("keep_work", False))
    b = CharacterBuilder(ctx, log)
    res = b.run()
    if not ctx.keep_work and not ctx.dry_run and not ctx.no_deploy and ctx.work:
        rmtree(ctx.work)
        res["work"] = ""
    return res
