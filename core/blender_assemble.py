"""Headless Blender script: Imports WW .uemodel + .ueanim + RibbonAnim + v10 Shape Key curves,
applies Wuthering Waves Toon Shader (Blender 3.6/4.x/5.x safe), renders multi-angle/multi-frame
motion previews, saves ready-to-play showcase .blend, exports & round-trip verifies handoff .fbx!

Invoked by blender_runner.py as:
  blender --background --factory-startup --python blender_assemble.py -- <job.json> <result.json>
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import addon_utils
import bpy
from mathutils import Euler, Quaternion, Vector

_SHORT_STAGE_DIR: Optional[Path] = None
_SHORT_STAGE_CACHE: Dict[str, str] = {}


def _win_ext_path(p: str) -> str:
    ps = os.path.abspath(p)
    if os.name == "nt" and len(ps) >= 240 and not ps.startswith("\\\\?\\"):
        return "\\\\?\\" + ps
    return ps


def stage_for_blender(filepath: str) -> str:
    """Guarantee a Windows path < 200 chars for Blender/UEFormat (prevents MAX_PATH=260 FileNotFoundError)."""
    if not filepath or os.name != "nt" or len(os.path.abspath(filepath)) < 200:
        return filepath
    key = os.path.normcase(os.path.abspath(filepath))
    if key in _SHORT_STAGE_CACHE:
        return _SHORT_STAGE_CACHE[key]
    global _SHORT_STAGE_DIR
    if _SHORT_STAGE_DIR is None:
        _SHORT_STAGE_DIR = Path(tempfile.mkdtemp(prefix="ww_bl_"))
    src = _win_ext_path(filepath)
    tag = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    dst = _SHORT_STAGE_DIR / f"{tag}_{Path(filepath).name}"
    if not dst.exists():
        try:
            os.link(src, str(dst))
        except OSError:
            shutil.copy2(src, str(dst))
    _SHORT_STAGE_CACHE[key] = str(dst)
    return str(dst)

HAIR_MASK_TOKENS = ("alpha", "lash", "eyelash", "heta", "trans")
SWITCH_TOKEN = "_switch"
ALPHA_CLIP_THRESHOLD = 0.333
TOON_SHADOW_COLOR = (0.36, 0.32, 0.42, 1.0)
SHAPE_KEY_IGNORE_PREFIXES = ("ik_", "foot_", "landingtime", "mor_", "morpher_", "weight_", "footstate")


# ============================================================================
# Blender 3.6 / 4.x / 5.x Cross-Version Compatibility Layer
# ============================================================================

def get_action_fcurves(action) -> List[Any]:
    """Read all F-Curves from an Action across Blender 3.6, 4.x, and 5.x slotted actions."""
    if action is None:
        return []
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return list(legacy)
    curves: List[Any] = []
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for cb in getattr(strip, "channelbags", ()):
                curves.extend(getattr(cb, "fcurves", ()))
    return curves


def get_or_create_fcurve_collection(action, target_id):
    """Return writable fcurves collection on Action for Blender 3.6/4.x/5.x."""
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return legacy
    # Blender 4.4+/5.x layered/slotted action API
    slot = None
    id_type = target_id.id_type if hasattr(target_id, "id_type") else "OBJECT"
    for s in getattr(action, "slots", ()):
        if getattr(s, "target_id_type", None) == id_type:
            slot = s
            break
    if slot is None:
        slot = action.slots.new(id_type=id_type, name=getattr(target_id, "name", "Slot"))
    if target_id.animation_data is None:
        target_id.animation_data_create()
    target_id.animation_data.action = action
    if hasattr(target_id.animation_data, "action_slot"):
        try:
            target_id.animation_data.action_slot = slot
        except Exception:
            pass
    layer = action.layers[0] if len(action.layers) > 0 else action.layers.new("Layer")
    strip = layer.strips[0] if len(layer.strips) > 0 else layer.strips.new(type="KEYFRAME")
    cb = strip.channelbag(slot, ensure=True)
    return cb.fcurves


def remove_fcurves_matching(action, predicate) -> int:
    """Delete F-Curves matching predicate across Blender 3.6/4.x/5.x."""
    if action is None:
        return 0
    removed = 0
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        victims = [fc for fc in list(legacy) if predicate(fc)]
        for fc in victims:
            legacy.remove(fc)
            removed += 1
        return removed
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for cb in getattr(strip, "channelbags", ()):
                fcs = cb.fcurves
                victims = [fc for fc in list(fcs) if predicate(fc)]
                for fc in victims:
                    fcs.remove(fc)
                    removed += 1
    return removed


def select_pose_bone_compat(armature, pose_bone, state: bool) -> None:
    if hasattr(pose_bone, "select"):
        pose_bone.select = state
    if hasattr(pose_bone, "bone") and hasattr(pose_bone.bone, "select"):
        pose_bone.bone.select = state


_BONE_DP_RE = re.compile(r'pose\.bones\["([^"]+)"\]')
_CYCLIC_ANIM_TOKENS = ("walk", "run", "sprint", "loop", "idle", "stand_loop")


def _infer_channel_group_name(data_path: str) -> str:
    m = _BONE_DP_RE.search(data_path or "")
    if m:
        return m.group(1)
    if "key_blocks[" in (data_path or ""):
        return "Shape Keys"
    return "Object Transforms"


def ensure_action_channel_groups(action) -> Dict[str, int]:
    """Ensure 100% of F-Curves belong to a named channel group (fixes ISS-008 in Blender 5.x/4.x/3.6!)."""
    if action is None:
        return {"groups": 0, "total_fcurves": 0, "grouped_fcurves": 0}

    total_fcs = 0
    grouped_fcs = 0
    group_names: set[str] = set()

    def _assign_bag(fcurves_coll, groups_coll) -> None:
        nonlocal total_fcs, grouped_fcs
        existing = {g.name: g for g in groups_coll}
        for fc in fcurves_coll:
            total_fcs += 1
            if fc.group is None:
                gname = _infer_channel_group_name(fc.data_path)
                grp = existing.get(gname)
                if grp is None:
                    grp = groups_coll.new(gname)
                    existing[gname] = grp
                fc.group = grp
            if fc.group is not None:
                grouped_fcs += 1
                group_names.add(fc.group.name)

    legacy_fcs = getattr(action, "fcurves", None)
    legacy_grps = getattr(action, "groups", None)
    if legacy_fcs is not None and legacy_grps is not None:
        _assign_bag(legacy_fcs, legacy_grps)
    else:
        for layer in getattr(action, "layers", ()):
            for strip in getattr(layer, "strips", ()):
                for cb in getattr(strip, "channelbags", ()):
                    _assign_bag(cb.fcurves, cb.groups)

    return {
        "groups": len(group_names),
        "total_fcurves": total_fcs,
        "grouped_fcurves": grouped_fcs,
    }


def compute_action_keyframe_bounds(action) -> Optional[Tuple[int, int]]:
    """Return exact (min_frame, max_frame) directly from F-Curve keyframes, or None if action has 0 keyframes."""
    if action is None:
        return None
    fmin = None
    fmax = None
    for fc in get_action_fcurves(action):
        kps = getattr(fc, "keyframe_points", None)
        if not kps or len(kps) == 0:
            continue
        x0 = float(kps[0].co[0])
        x1 = float(kps[-1].co[0])
        lo = min(x0, x1)
        hi = max(x0, x1)
        fmin = lo if fmin is None else min(fmin, lo)
        fmax = hi if fmax is None else max(fmax, hi)
    if fmin is None or fmax is None:
        return None
    return int(math.floor(fmin)), max(int(math.floor(fmin)), int(math.ceil(fmax)))


def configure_action_metadata(action, *, is_shape_key: bool = False) -> Tuple[int, int]:
    """Set fake user, channel groups, manual frame range, and cyclic hint on an Action."""
    if action is None:
        return (0, 60)
    action.use_fake_user = True
    ensure_action_channel_groups(action)
    bounds = compute_action_keyframe_bounds(action)
    if bounds is not None:
        f0, f1 = bounds
    elif getattr(action, "frame_range", None):
        f0 = int(round(action.frame_range[0]))
        f1 = max(f0, int(round(action.frame_range[1])))
    else:
        f0, f1 = 0, 60

    if hasattr(action, "use_frame_range"):
        action.use_frame_range = True
        action.frame_start = float(f0)
        action.frame_end = float(f1)
    if not is_shape_key and hasattr(action, "use_cyclic"):
        nlow = action.name.lower()
        action.use_cyclic = any(tok in nlow for tok in _CYCLIC_ANIM_TOKENS)
    return (f0, f1)


def bind_action_with_slot(target_id, action) -> None:
    """Safely bind `action` (and its matching Blender 4.4+/5.x slot) onto `target_id`."""
    if target_id is None:
        return
    if action is None:
        if target_id.animation_data is not None:
            target_id.animation_data.action = None
        return
    if target_id.animation_data is None:
        target_id.animation_data_create()
    target_id.animation_data.action = action
    if hasattr(target_id.animation_data, "action_slot") and hasattr(action, "slots"):
        id_type = getattr(target_id, "id_type", "OBJECT")
        for s in action.slots:
            if getattr(s, "target_id_type", None) == id_type:
                try:
                    target_id.animation_data.action_slot = s
                except Exception:
                    pass
                break


_WW_ACTION_SYNC_SCRIPT = r'''"""WW Showcase Auto-Sync (ISS-009 + ISS-005):
Automatically syncs Scene Frame Range (`frame_start` / `frame_end`) AND matching facial
`*_ShapeKeys` Action whenever the Armature's active Action or Slot changes.
Also provides a convenient `WW Showcase` sidebar panel in 3D View.
"""
import json
import math
import bpy
from bpy.app.handlers import persistent

_STATE = {"last_key": None, "busy": False}


def _iter_action_fcurves(action):
    if action is None:
        return []
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return list(legacy)
    out = []
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for cb in getattr(strip, "channelbags", ()):
                out.extend(getattr(cb, "fcurves", ()))
    return out


def _get_action_keyframe_bounds(action):
    fmin = None
    fmax = None
    for fc in _iter_action_fcurves(action):
        kps = getattr(fc, "keyframe_points", None)
        if not kps or len(kps) == 0:
            continue
        x0 = float(kps[0].co[0])
        x1 = float(kps[-1].co[0])
        lo = min(x0, x1)
        hi = max(x0, x1)
        fmin = lo if fmin is None else min(fmin, lo)
        fmax = hi if fmax is None else max(fmax, hi)
    if fmin is None or fmax is None:
        return None
    return int(math.floor(fmin)), max(int(math.floor(fmin)), int(math.ceil(fmax)))


def _find_character_armature(scene):
    obj = getattr(bpy.context, "active_object", None)
    if obj and obj.type == "ARMATURE":
        return obj
    arm = bpy.data.objects.get("Armature")
    if arm and arm.type == "ARMATURE":
        return arm
    if scene:
        for o in scene.objects:
            if o.type == "ARMATURE":
                return o
    return None


def _bind_key_action(sk, sk_act):
    if sk is None:
        return
    for kb in sk.key_blocks:
        if kb.name != "Basis":
            kb.value = 0.0
    if sk_act is None:
        if sk.animation_data is not None:
            sk.animation_data.action = None
        return
    if sk.animation_data is None:
        sk.animation_data_create()
    sk.animation_data.action = sk_act
    if hasattr(sk.animation_data, "action_slot") and hasattr(sk_act, "slots"):
        for s in sk_act.slots:
            if getattr(s, "target_id_type", None) == "KEY":
                try:
                    sk.animation_data.action_slot = s
                except Exception:
                    pass
                break


def sync_scene_and_face_to_armature(scene, force=False):
    if _STATE["busy"] or scene is None:
        return False
    if not force and not scene.get("ww_auto_sync_enabled", True):
        return False
    arm = _find_character_armature(scene)
    if arm is None or arm.animation_data is None:
        return False

    act = arm.animation_data.action
    slot_handle = None
    if hasattr(arm.animation_data, "action_slot") and arm.animation_data.action_slot is not None:
        slot_handle = getattr(arm.animation_data.action_slot, "handle", None)
    key = (arm.name, act.name if act else None, slot_handle)
    if not force and _STATE["last_key"] == key:
        return False

    _STATE["busy"] = True
    try:
        _STATE["last_key"] = key
        if act is None:
            return False

        # Ignore ShapeKey actions if user accidentally picked one onto Armature
        if act.name.endswith("_ShapeKeys"):
            return False

        # 1. Sync scene start/end strictly to real F-Curve keyframe range (ISS-009)
        bounds = _get_action_keyframe_bounds(act)
        if bounds is not None:
            f0, f1 = bounds
            if scene.frame_start != f0:
                scene.frame_start = f0
            if scene.frame_end != f1:
                scene.frame_end = f1
            if scene.frame_current < f0 or scene.frame_current > f1:
                scene.frame_set(f0)

        # 2. Sync paired facial *_ShapeKeys actions onto every mesh parented to this Armature (ISS-005)
        raw_map = arm.get("ww_action_sk_map")
        sk_map_all = json.loads(raw_map) if isinstance(raw_map, str) and raw_map else {}
        per_mesh = sk_map_all.get(act.name) if isinstance(sk_map_all, dict) else None
        for obj in bpy.data.objects:
            if obj.type != "MESH" or not obj.data.shape_keys:
                continue
            linked = (obj.parent == arm) or any(
                m.type == "ARMATURE" and m.object == arm for m in obj.modifiers
            )
            if not linked:
                continue
            sk_name = None
            if isinstance(per_mesh, dict):
                sk_name = per_mesh.get(obj.name)
            if not sk_name:
                cand = f"{act.name}_ShapeKeys"
                if cand in bpy.data.actions:
                    sk_name = cand
            sk_act = bpy.data.actions.get(sk_name) if sk_name else None
            _bind_key_action(obj.data.shape_keys, sk_act)
        return True
    finally:
        _STATE["busy"] = False


@persistent
def _on_depsgraph_update(scene, depsgraph=None):
    sync_scene_and_face_to_armature(scene, force=False)


@persistent
def _on_frame_change_pre(scene, depsgraph=None):
    sync_scene_and_face_to_armature(scene, force=False)


@persistent
def _on_load_post(_dummy):
    _STATE["last_key"] = None
    if bpy.context.scene:
        sync_scene_and_face_to_armature(bpy.context.scene, force=True)


class WW_OT_SwitchAction(bpy.types.Operator):
    bl_idname = "ww.switch_action"
    bl_label = "Switch WW Action"
    bl_description = "Switch character body action and auto-sync timeline range + facial shape keys"
    action_name: bpy.props.StringProperty()

    def execute(self, context):
        arm = _find_character_armature(context.scene)
        act = bpy.data.actions.get(self.action_name)
        if arm is None or act is None:
            return {"CANCELLED"}
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = act
        if hasattr(arm.animation_data, "action_slot") and hasattr(act, "slots"):
            for s in act.slots:
                if getattr(s, "target_id_type", None) == "OBJECT":
                    try:
                        arm.animation_data.action_slot = s
                    except Exception:
                        pass
                    break
        sync_scene_and_face_to_armature(context.scene, force=True)
        return {"FINISHED"}


class WW_OT_SyncNow(bpy.types.Operator):
    bl_idname = "ww.sync_action_range_now"
    bl_label = "Sync Frame Range & Face"

    def execute(self, context):
        sync_scene_and_face_to_armature(context.scene, force=True)
        return {"FINISHED"}


class WW_OT_ToggleAutoSync(bpy.types.Operator):
    bl_idname = "ww.toggle_auto_sync"
    bl_label = "Toggle Auto Sync"

    def execute(self, context):
        cur = bool(context.scene.get("ww_auto_sync_enabled", True))
        context.scene["ww_auto_sync_enabled"] = not cur
        if not cur:
            sync_scene_and_face_to_armature(context.scene, force=True)
        return {"FINISHED"}


class WW_PT_ShowcasePanel(bpy.types.Panel):
    bl_label = "WW Showcase"
    bl_idname = "WW_PT_showcase_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WW Showcase"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        arm = _find_character_armature(scene)
        if arm is None:
            layout.label(text="No Armature found")
            return

        auto_on = bool(scene.get("ww_auto_sync_enabled", True))
        row = layout.row(align=True)
        row.operator("ww.toggle_auto_sync", text=f"Auto Sync: {'ON' if auto_on else 'OFF'}", depress=auto_on)
        row.operator("ww.sync_action_range_now", text="Sync Now")

        cur_act = arm.animation_data.action.name if (arm.animation_data and arm.animation_data.action) else "(None)"
        layout.label(text=f"Active: {cur_act} ({scene.frame_start}..{scene.frame_end})")

        box = layout.box()
        box.label(text="Body Actions (Auto Face + Range):")
        raw_list = arm.get("ww_body_actions")
        names = json.loads(raw_list) if isinstance(raw_list, str) and raw_list else [
            a.name for a in bpy.data.actions if not a.name.endswith("_ShapeKeys")
        ]
        for an in names:
            if an in bpy.data.actions:
                op = box.operator("ww.switch_action", text=an, depress=(an == cur_act))
                op.action_name = an

        box2 = layout.box()
        box2.label(text="Skeleton Display:")
        box2.prop(arm, "show_in_front", text="Show Bones In Front")
        if hasattr(arm.data, "collections"):
            for bc in arm.data.collections:
                box2.prop(bc, "is_visible", text=f"{bc.name} ({len(bc.bones)})")


def _register_handler(handler_list, fn, tag):
    for existing in list(handler_list):
        if getattr(existing, "_ww_sync_tag", None) == tag:
            handler_list.remove(existing)
    fn._ww_sync_tag = tag
    handler_list.append(fn)


def register():
    for cls in (WW_OT_SwitchAction, WW_OT_SyncNow, WW_OT_ToggleAutoSync, WW_PT_ShowcasePanel):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    _register_handler(bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update, "ww_depsgraph_sync")
    _register_handler(bpy.app.handlers.frame_change_pre, _on_frame_change_pre, "ww_frame_sync")
    _register_handler(bpy.app.handlers.load_post, _on_load_post, "ww_load_sync")


register()
'''


def embed_action_sync_script(armature, body_action_names: List[str], action_sk_map: Dict[str, Dict[str, str]]) -> None:
    """Embed auto-executing `ww_action_sync.py` (use_module=True) & action metadata into the .blend."""
    armature["ww_body_actions"] = json.dumps(body_action_names, ensure_ascii=False)
    armature["ww_action_sk_map"] = json.dumps(action_sk_map, ensure_ascii=False)
    bpy.context.scene["ww_auto_sync_enabled"] = True

    txt = bpy.data.texts.get("ww_action_sync.py")
    if txt is None:
        txt = bpy.data.texts.new("ww_action_sync.py")
    txt.clear()
    txt.from_string(_WW_ACTION_SYNC_SCRIPT)
    txt.use_module = True
    # Execute once right now so handlers & panel are active in the current session too
    try:
        ns: Dict[str, Any] = {"__name__": "ww_action_sync"}
        exec(compile(_WW_ACTION_SYNC_SCRIPT, "ww_action_sync.py", "exec"), ns)
    except Exception:
        pass


# ============================================================================
# UEFormat v10 .ueanim Curve Reader (Facial Shape Keys / Morph Targets)
# ============================================================================

def read_ueanim_curves(filepath: str) -> Dict[str, Any]:
    raw = Path(_win_ext_path(filepath)).read_bytes()
    pos = 0

    def r(n: int) -> bytes:
        nonlocal pos
        if pos + n > len(raw):
            raise EOFError("Unexpected EOF in .ueanim")
        s = raw[pos : pos + n]
        pos += n
        return s

    def ri() -> int:
        return struct.unpack("<i", r(4))[0]

    def rf() -> float:
        return struct.unpack("<f", r(4))[0]

    def rfs() -> str:
        ln = ri()
        if ln < 0:
            raise ValueError("UTF-16 FString unsupported")
        return r(ln).rstrip(b"\x00").decode("utf-8", errors="replace")

    magic = r(8).decode("ascii", errors="replace")
    if magic != "UEFORMAT":
        raise ValueError(f"Not UEFORMAT: {magic!r}")
    ident = rfs()
    if ident != "UEANIM":
        raise ValueError(f"Not UEANIM: {ident!r}")
    ver = r(1)[0]
    anim_name = rfs()
    if ver >= 10:
        _obj_path = rfs()

    is_comp = bool(r(1)[0])
    payload = raw
    ppos = pos
    if is_comp:
        ctype = rfs()
        usize = ri()
        _csize = ri()
        comp_bytes = raw[pos:]
        if ctype == "GZIP":
            payload = gzip.decompress(comp_bytes)
        elif ctype == "ZSTD":
            import zstandard as zstd

            payload = zstd.ZstdDecompressor().decompress(comp_bytes, max_output_size=usize)
        else:
            raise ValueError(f"Unsupported .ueanim compression: {ctype}")
        ppos = 0

    def pr(n: int) -> bytes:
        nonlocal ppos
        s = payload[ppos : ppos + n]
        ppos += n
        return s

    def pri() -> int:
        return struct.unpack("<i", pr(4))[0]

    def prf() -> float:
        return struct.unpack("<f", pr(4))[0]

    def prfs() -> str:
        ln = pri()
        return pr(ln).rstrip(b"\x00").decode("utf-8", errors="replace")

    num_frames = 0
    fps = 30.0
    curves: List[Dict[str, Any]] = []

    if ver >= 10:
        attr_count = pri()
        for _ in range(attr_count):
            if ppos >= len(payload):
                break
            sname = prfs()
            bsz = pri()
            end = min(len(payload), ppos + bsz)
            if sname == "METADATA":
                num_frames = pri()
                fps = prf()
            elif sname == "CURVES":
                cnt = pri()
                for _c in range(cnt):
                    cname = prfs()
                    kc = pri()
                    keys = [(pri(), prf()) for _k in range(kc)]
                    curves.append({"name": cname, "keys": keys})
            ppos = end

    return {"name": anim_name, "version": ver, "num_frames": num_frames, "fps": fps, "curves": curves}


def apply_shape_key_curves(mesh_obj, anim_data: Dict[str, Any], action_name: str) -> Dict[str, Any]:
    """Write .ueanim CURVES onto mesh shape_keys (Blender 3.6/4.x/5.x compatible)."""
    if not mesh_obj.data.shape_keys or not anim_data.get("curves"):
        return {"matched_curves": 0, "inserted_keyframes": 0}

    sk = mesh_obj.data.shape_keys
    kb_map = {kb.name.lower(): kb.name for kb in sk.key_blocks}
    action = bpy.data.actions.new(name=f"{action_name}_ShapeKeys")
    if sk.animation_data is None:
        sk.animation_data_create()
    sk.animation_data.action = action
    fcurves = get_or_create_fcurve_collection(action, sk)

    matched = 0
    total_kf = 0
    for curve in anim_data["curves"]:
        cname = curve["name"]
        clow = cname.lower()
        if any(clow.startswith(pfx) for pfx in SHAPE_KEY_IGNORE_PREFIXES):
            continue
        target_name = kb_map.get(clow)
        if target_name is None:
            continue
        keys = curve.get("keys") or []
        if not keys:
            continue
        dp = f'key_blocks["{target_name}"].value'
        fc = next((f for f in fcurves if f.data_path == dp), None)
        if fc is None:
            fc = fcurves.new(data_path=dp)
        # Ensure min/max allows curve values
        kb = sk.key_blocks[target_name]
        vals = [v for _, v in keys]
        if min(vals) < kb.slider_min:
            kb.slider_min = min(vals)
        if max(vals) > kb.slider_max:
            kb.slider_max = max(vals)
        for frame_idx, val in keys:
            # Align strictly 0-based with io_scene_ueformat bone keyframes (no +1 frame drift!)
            fc.keyframe_points.insert(frame=float(frame_idx), value=float(val), options={"FAST"})
            total_kf += 1
        fc.update()
        matched += 1

    if matched == 0:
        sk.animation_data.action = None
        bpy.data.actions.remove(action)
        return {"matched_curves": 0, "inserted_keyframes": 0, "action_name": None}

    # Preserve non-default facial animations across .blend save + build 'Shape Keys' channel group (ISS-005 + ISS-008)
    configure_action_metadata(action, is_shape_key=True)
    return {"matched_curves": matched, "inserted_keyframes": total_kf, "action_name": action.name}


# ============================================================================
# RibbonAnim Merging & Physics Baking
# ============================================================================

def merge_ribbon_action_into_body(body_action, ribbon_action, target_armature) -> int:
    """Copy Bone* F-Curves from a RibbonAnim Action into the matching body Action."""
    if body_action is None or ribbon_action is None:
        return 0
    # First remove any existing Bone* curves in body_action so ribbon curves cleanly take over
    remove_fcurves_matching(body_action, lambda fc: 'pose.bones["Bone' in fc.data_path)
    dst_fcurves = get_or_create_fcurve_collection(body_action, target_armature)
    copied = 0
    for src_fc in get_action_fcurves(ribbon_action):
        if 'pose.bones["Bone' not in src_fc.data_path:
            continue
        dst_fc = dst_fcurves.new(data_path=src_fc.data_path, index=src_fc.array_index)
        for kp in src_fc.keyframe_points:
            dst_fc.keyframe_points.insert(frame=kp.co[0], value=kp.co[1], options={"FAST"})
        dst_fc.update()
        copied += 1
    return copied


def bake_bone_physics_fallback(armature, start_frame: int, end_frame: int) -> int:
    """Apply zero-twist rest-frame inertial spring sway on Bone* chains when no matching RibbonAnim exists.

    Unlike Blender's default DAMPED_TRACK(TRACK_Y) — which twists UE +X-axis bones by ~90 deg —
    this samples parent world velocity and keys small damped local Euler/Quaternion deltas (<= 6 deg)
    around each bone's exact rest orientation so pigtails, ribbons, and skirts drape naturally!
    """
    cur_act = armature.animation_data.action if armature.animation_data else None
    if cur_act is None:
        return 0

    phys_bones = [b for b in armature.pose.bones if b.name.startswith("Bone")]
    if not phys_bones:
        return 0

    # Group into chains rooted on a non-Bone* body bone (e.g. Bip001Head, Bip001Pelvis)
    phys_set = {b.name for b in phys_bones}
    depth_map: Dict[str, int] = {}
    root_anchor_map: Dict[str, Optional[str]] = {}
    for b in phys_bones:
        d = 0
        cur = b
        while cur.parent and cur.parent.name in phys_set:
            d += 1
            cur = cur.parent
        depth_map[b.name] = d
        root_anchor_map[b.name] = cur.parent.name if cur.parent else None

    end_clamped = min(end_frame, start_frame + 120)
    frames = list(range(start_frame, end_clamped + 1))
    if len(frames) < 3:
        return 0

    # Sample unique anchor bones' world positions per frame
    anchors = sorted({a for a in root_anchor_map.values() if a})
    anchor_pos: Dict[str, List[Vector]] = {a: [] for a in anchors}
    for fr in frames:
        bpy.context.scene.frame_set(fr)
        bpy.context.view_layer.update()
        for a in anchors:
            pb = armature.pose.bones.get(a)
            anchor_pos[a].append((armature.matrix_world @ pb.head).copy() if pb else Vector((0, 0, 0)))

    # Compute smoothed inertial sway angle (radians) from anchor vertical/horizontal acceleration
    fcurves = get_or_create_fcurve_collection(cur_act, armature)
    baked_count = 0
    for b in phys_bones:
        anchor = root_anchor_map.get(b.name)
        if not anchor or anchor not in anchor_pos:
            continue
        pos_list = anchor_pos[anchor]
        depth = depth_map.get(b.name, 0)
        amp = min(0.10, 0.025 + 0.015 * depth)  # <= ~5.7 deg max sway, zero rest-axis twist!
        phase = depth * 0.55

        b.rotation_mode = "QUATERNION"
        dp = f'pose.bones["{b.name}"].rotation_quaternion'
        # Remove any prior rotation_quaternion curves for this bone
        remove_fcurves_matching(cur_act, lambda fc, target=dp: fc.data_path == target)
        q_fcs = [fcurves.new(data_path=dp, index=i) for i in range(4)]

        # Smooth spring state
        sway_x = 0.0
        sway_z = 0.0
        vel_x = 0.0
        vel_z = 0.0
        for idx, fr in enumerate(frames):
            if idx == 0:
                acc_y, acc_z = 0.0, 0.0
            else:
                dv = pos_list[idx] - pos_list[idx - 1]
                acc_y = max(-0.08, min(0.08, dv.y))
                acc_z = max(-0.08, min(0.08, dv.z))
            # Critically damped spring driven by anchor motion + subtle chain wave
            target_x = max(-amp, min(amp, -acc_y * 1.4 + math.sin(idx * 0.25 - phase) * amp * 0.35))
            target_z = max(-amp, min(amp, acc_z * 1.1 + math.cos(idx * 0.22 - phase) * amp * 0.25))
            vel_x = vel_x * 0.72 + (target_x - sway_x) * 0.28
            vel_z = vel_z * 0.72 + (target_z - sway_z) * 0.28
            sway_x = max(-amp, min(amp, sway_x + vel_x))
            sway_z = max(-amp, min(amp, sway_z + vel_z))

            q = Euler((sway_x, 0.0, sway_z), "XYZ").to_quaternion()
            for ci in range(4):
                q_fcs[ci].keyframe_points.insert(frame=float(fr), value=float(q[ci]), options={"FAST"})

        for fc in q_fcs:
            fc.update()
        baked_count += 1

    return baked_count


# ============================================================================
# Wuthering Waves Toon Shader Builder (Blender 3.6/4.x/5.x Compatible)
# ============================================================================

def ensure_ww_toon_node_group():
    name = "WW_Toon_Showcase_Shader"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    ng = bpy.data.node_groups.new(type="ShaderNodeTree", name=name)
    is_b4 = bpy.app.version >= (4, 0, 0)

    def _add_socket(sock_name: str, in_out: str, sock_type: str, default=None):
        if is_b4 and hasattr(ng, "interface"):
            s = ng.interface.new_socket(name=sock_name, in_out=in_out, socket_type=sock_type)
        else:
            # Blender 3.6 legacy NodeTree inputs/outputs API
            coll = ng.inputs if in_out == "INPUT" else ng.outputs
            s = coll.new(sock_type, sock_name)
        if default is not None and hasattr(s, "default_value"):
            s.default_value = default
        return s

    _add_socket("Shader", "OUTPUT", "NodeSocketShader")
    _add_socket("BaseColor", "INPUT", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    _add_socket("NormalColor", "INPUT", "NodeSocketColor", (0.5, 0.5, 1.0, 1.0))
    _add_socket("UseNormal", "INPUT", "NodeSocketFloat", 0.0)
    _add_socket("Alpha", "INPUT", "NodeSocketFloat", 1.0)
    _add_socket("UseAlphaClip", "INPUT", "NodeSocketFloat", 0.0)
    _add_socket("AlphaThreshold", "INPUT", "NodeSocketFloat", ALPHA_CLIP_THRESHOLD)
    _add_socket("ShadowTint", "INPUT", "NodeSocketColor", TOON_SHADOW_COLOR)
    _add_socket("Brightness", "INPUT", "NodeSocketFloat", 1.15)

    nodes = ng.nodes
    links = ng.links

    def _new_rgba_mix(blend_type: str = "MIX", loc: Tuple[int, int] = (0, 0)):
        """Cross-version RGBA mix helper returning (node, fac_in, a_in, b_in, out_sock)."""
        if is_b4:
            n = nodes.new("ShaderNodeMix")
            n.data_type = "RGBA"
            n.blend_type = blend_type
            n.location = loc
            return n, n.inputs["Factor"], n.inputs["A"], n.inputs["B"], n.outputs["Result"]
        n = nodes.new("ShaderNodeMixRGB")
        n.blend_type = blend_type
        n.location = loc
        return n, n.inputs["Fac"], n.inputs["Color1"], n.inputs["Color2"], n.outputs["Color"]

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-900, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (700, 0)

    # Convert DirectX Normal (RG, G=-Y) -> OpenGL Normal (R, 1-G, 1.0)
    sep_n = nodes.new("ShaderNodeSeparateColor")
    sep_n.location = (-680, -180)
    inv_g = nodes.new("ShaderNodeMath")
    inv_g.operation = "SUBTRACT"
    inv_g.inputs[0].default_value = 1.0
    inv_g.location = (-500, -180)
    comb_n = nodes.new("ShaderNodeCombineColor")
    comb_n.inputs[2].default_value = 1.0
    comb_n.location = (-320, -180)
    nmap = nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = 0.55
    nmap.location = (-140, -180)

    geom = nodes.new("ShaderNodeNewGeometry")
    geom.location = (-320, -380)

    # Select geometry normal vs normal-mapped normal (ShaderNodeMix exists in 3.4+ for VECTOR/FLOAT)
    mix_n = nodes.new("ShaderNodeMix")
    mix_n.data_type = "VECTOR"
    mix_n.location = (60, -240)

    # Key light direction vector (studio front-top-right)
    light_dir = nodes.new("ShaderNodeCombineXYZ")
    light_dir.inputs[0].default_value = 0.35
    light_dir.inputs[1].default_value = -0.78
    light_dir.inputs[2].default_value = 0.52
    light_dir.location = (-140, -440)

    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.location = (240, -320)

    # Smooth cel ramp (soft anime shadow band)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (240, -80)
    ramp.color_ramp.interpolation = "EASE"
    ramp.color_ramp.elements[0].position = 0.02
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    ramp.color_ramp.elements[1].position = 0.28
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)

    # Shadow color = BaseColor * ShadowTint (soft cool shadow, never crushed black)
    _mul_node, mul_fac, mul_a, mul_b, mul_out = _new_rgba_mix("MULTIPLY", (20, 160))
    mul_fac.default_value = 0.58

    # Mix shadow and lit BaseColor by cel ramp
    _cel_node, cel_fac, cel_a, cel_b, cel_out = _new_rgba_mix("MIX", (260, 180))

    # Subtle Fresnel rim highlight for crisp anime silhouette
    lw = nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.22
    lw.location = (20, 380)
    _rim_node, rim_fac, rim_a, rim_b, rim_out = _new_rgba_mix("ADD", (380, 220))
    rim_b.default_value = (0.14, 0.14, 0.17, 1.0)

    # Emission toon output (immune to harsh dark EEVEE shadows, clean anime look)
    emis = nodes.new("ShaderNodeEmission")
    emis.location = (440, 40)

    # Optional Alpha Clip (ONLY enabled for Masked/Hair slots!)
    transp = nodes.new("ShaderNodeBsdfTransparent")
    transp.location = (440, -140)
    cmp_alpha = nodes.new("ShaderNodeMath")
    cmp_alpha.operation = "GREATER_THAN"
    cmp_alpha.location = (180, -520)
    mix_clip = nodes.new("ShaderNodeMix")
    mix_clip.data_type = "FLOAT"
    mix_clip.inputs["A"].default_value = 1.0  # when UseAlphaClip=0 -> always 1.0 (opaque)
    mix_clip.location = (360, -480)
    mix_shader = nodes.new("ShaderNodeMixShader")
    mix_shader.location = (560, 0)

    # Links
    links.new(n_in.outputs["NormalColor"], sep_n.inputs["Color"])
    links.new(sep_n.outputs["Red"], comb_n.inputs["Red"])
    links.new(sep_n.outputs["Green"], inv_g.inputs[1])
    links.new(inv_g.outputs["Value"], comb_n.inputs["Green"])
    links.new(comb_n.outputs["Color"], nmap.inputs["Color"])

    links.new(n_in.outputs["UseNormal"], mix_n.inputs["Factor"])
    links.new(geom.outputs["Normal"], mix_n.inputs["A"])
    links.new(nmap.outputs["Normal"], mix_n.inputs["B"])

    links.new(mix_n.outputs["Result"], dot.inputs[0])
    links.new(light_dir.outputs["Vector"], dot.inputs[1])
    links.new(dot.outputs["Value"], ramp.inputs["Fac"])

    links.new(n_in.outputs["BaseColor"], mul_a)
    links.new(n_in.outputs["ShadowTint"], mul_b)

    links.new(ramp.outputs["Color"], cel_fac)
    links.new(mul_out, cel_a)
    links.new(n_in.outputs["BaseColor"], cel_b)

    links.new(lw.outputs["Facing"], rim_fac)
    links.new(cel_out, rim_a)

    links.new(rim_out, emis.inputs["Color"])
    links.new(n_in.outputs["Brightness"], emis.inputs["Strength"])

    links.new(n_in.outputs["Alpha"], cmp_alpha.inputs[0])
    links.new(n_in.outputs["AlphaThreshold"], cmp_alpha.inputs[1])
    links.new(n_in.outputs["UseAlphaClip"], mix_clip.inputs["Factor"])
    links.new(cmp_alpha.outputs["Value"], mix_clip.inputs["B"])

    links.new(mix_clip.outputs["Result"], mix_shader.inputs["Fac"])
    links.new(transp.outputs["BSDF"], mix_shader.inputs[1])
    links.new(emis.outputs["Emission"], mix_shader.inputs[2])
    links.new(mix_shader.outputs["Shader"], n_out.inputs["Shader"])

    return ng


def _load_image_once(filepath: str, colorspace: str, alpha_mode: str = "CHANNEL_PACKED"):
    filepath = stage_for_blender(filepath)
    abs_p = os.path.normcase(os.path.abspath(filepath))
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(os.path.abspath(bpy.path.abspath(img.filepath))) == abs_p:
            img.colorspace_settings.name = colorspace
            img.alpha_mode = alpha_mode
            return img
    img = bpy.data.images.load(filepath, check_existing=True)
    img.colorspace_settings.name = colorspace
    img.alpha_mode = alpha_mode
    return img


def apply_materials_from_audit(mesh_objs: List[Any], audit_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build WW Toon Showcase materials on every mesh slot using Tier 1 MI JSON + Tier 2 fallback."""
    toon_ng = ensure_ww_toon_node_group()
    mi_catalog: Dict[str, Any] = audit_data.get("materials", {})
    tex_by_stem: Dict[str, Dict[str, Any]] = {}
    for t in audit_data.get("textures", []):
        tex_by_stem[t["name"].lower()] = t

    bound_report: List[Dict[str, Any]] = []
    unmatched_slots: List[str] = []
    is_b4 = bpy.app.version >= (4, 0, 0)

    for obj in mesh_objs:
        me = obj.data
        uv_names = [u.name for u in getattr(me, "uv_layers", ())]
        col_names = [c.name for c in getattr(me, "color_attributes", ())]
        if not col_names and hasattr(me, "vertex_colors"):
            col_names = [c.name for c in me.vertex_colors]
        vcol_layer_name = "COL0" if "COL0" in col_names else (col_names[0] if col_names else None)
        fur_uv_name = "UV2" if "UV2" in uv_names else (uv_names[2] if len(uv_names) > 2 else None)

        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            mat_base = re.sub(r"\.\d{3}$", "", mat.name)
            mi = mi_catalog.get(mat_base)
            if mi is None:
                # Case-insensitive lookup
                for mk, mv in mi_catalog.items():
                    if mk.lower() == mat_base.lower():
                        mi = mv
                        break

            base_tex_info = None
            normal_tex_info = None
            switch_tex_info = None
            type_mask_tex_info = None
            fur_card_tex_info = None
            hair_mask_tex_info = None
            is_hair_masked = any(tok in mat_base.lower() for tok in HAIR_MASK_TOKENS)
            is_fur_shader = False
            clip_val = ALPHA_CLIP_THRESHOLD
            mi_scalars = (mi.get("scalars") or {}) if mi else {}

            if mi:
                is_hair_masked = bool(mi.get("is_hair_or_masked", is_hair_masked))
                is_fur_shader = bool(mi.get("is_fur_shader", False))
                clip_val = float(mi.get("opacity_mask_clip_value", ALPHA_CLIP_THRESHOLD))
                for _pname, binfo in mi.get("bound_textures", {}).items():
                    tstem = binfo["texture_name"].lower()
                    trec = tex_by_stem.get(tstem)
                    if not trec:
                        continue
                    sem = binfo["semantic_slot"]
                    pname_low = _pname.lower()
                    if pname_low in ("fur_tex", "furtex") or sem == "fur_mask":
                        if "default" not in tstem and fur_card_tex_info is None:
                            fur_card_tex_info = trec
                    elif sem == "base_color":
                        if SWITCH_TOKEN in tstem:
                            switch_tex_info = trec
                        elif pname_low == "maintex" or base_tex_info is None:
                            # Prefer MainTex over PM_Diffuse when both are listed (e.g. Tail_D vs _M)
                            base_tex_info = trec
                    elif sem == "normal_packed" and normal_tex_info is None:
                        normal_tex_info = trec
                    elif (pname_low == "typemask" or sem == "id_mask") and type_mask_tex_info is None:
                        if "default" not in tstem and tstem != "white":
                            type_mask_tex_info = trec
                    elif (sem == "hair_mask" or tstem.endswith("_hm")) and hair_mask_tex_info is None:
                        if "default" not in tstem and not trec.get("pixel_audit", {}).get("all_zero"):
                            hair_mask_tex_info = trec

            # Tier 2 fallback by material name stem if Tier 1 missed (e.g. MI_6XingStar -> T_6XingStar_D)
            if base_tex_info is None:
                clean_key = re.sub(r"^mi_", "", mat_base, flags=re.IGNORECASE).lower()
                for tstem, trec in tex_by_stem.items():
                    if trec["slot"] == "base_color" and SWITCH_TOKEN not in tstem:
                        if clean_key and clean_key in tstem:
                            base_tex_info = trec
                            break
            if normal_tex_info is None:
                clean_key = re.sub(r"^mi_", "", mat_base, flags=re.IGNORECASE).lower()
                for tstem, trec in tex_by_stem.items():
                    if trec["slot"] == "normal_packed" and clean_key and clean_key in tstem:
                        normal_tex_info = trec
                        break

            # Build clean Toon node tree on material
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            out_n = nt.nodes.new("ShaderNodeOutputMaterial")
            out_n.location = (360, 0)
            grp = nt.nodes.new("ShaderNodeGroup")
            grp.node_tree = toon_ng
            grp.location = (40, 0)
            nt.links.new(grp.outputs["Shader"], out_n.inputs["Surface"])

            # Face gets slightly gentler shadow tint for clean anime face look
            if "face" in mat_base.lower():
                grp.inputs["ShadowTint"].default_value = (0.86, 0.78, 0.76, 1.0)
                grp.inputs["Brightness"].default_value = 1.08
            elif "eye" in mat_base.lower():
                grp.inputs["ShadowTint"].default_value = (0.92, 0.92, 0.95, 1.0)
                grp.inputs["Brightness"].default_value = 1.12

            grp.inputs["UseAlphaClip"].default_value = 0.0
            grp.inputs["AlphaThreshold"].default_value = clip_val

            # Determine whether TypeMask (_ID) carries a valid feathered fur silhouette (Red channel)
            fur_typemask_info = None
            if is_fur_shader and type_mask_tex_info is not None:
                ch_stats = type_mask_tex_info.get("pixel_audit", {}).get("channel_stats") or []
                if ch_stats:
                    r_nz_pct = float(ch_stats[0].get("nz_pct", 100.0))
                    r_max = float(ch_stats[0].get("max", 0))
                    if 5.0 <= r_nz_pct <= 92.0 and r_max > 20.0:
                        fur_typemask_info = type_mask_tex_info

            # Fallback: if a slot ONLY has a _Switch_ base texture, promote it rather than leaving flat gray!
            if base_tex_info is None and switch_tex_info is not None:
                base_tex_info = switch_tex_info
                switch_tex_info = None

            alpha_mode_used = "opaque"
            effective_alpha_enabled = False
            if base_tex_info:
                img_d = _load_image_once(base_tex_info["disk_path"], "sRGB", "CHANNEL_PACKED")
                tex_d = nt.nodes.new("ShaderNodeTexImage")
                tex_d.image = img_d
                tex_d.label = "Base Color (_D)"
                tex_d.location = (-360, 180)

                # Optional subtle hair angel-ring specular sheen when *_HM (Hair Mask) is available (ISS-003!)
                if hair_mask_tex_info and ("hair" in mat_base.lower() or "bang" in mat_base.lower()):
                    img_hm = _load_image_once(hair_mask_tex_info["disk_path"], "Non-Color", "CHANNEL_PACKED")
                    tex_hm = nt.nodes.new("ShaderNodeTexImage")
                    tex_hm.image = img_hm
                    tex_hm.label = "Hair Specular Mask (_HM)"
                    tex_hm.location = (-620, 420)
                    sep_hm = nt.nodes.new("ShaderNodeSeparateColor")
                    sep_hm.location = (-380, 420)
                    mul_hm = nt.nodes.new("ShaderNodeMath")
                    mul_hm.operation = "MULTIPLY"
                    mul_hm.use_clamp = True
                    mul_hm.inputs[1].default_value = 0.14
                    mul_hm.location = (-200, 420)
                    if is_b4:
                        mix_hm = nt.nodes.new("ShaderNodeMix")
                        mix_hm.data_type = "RGBA"
                        mix_hm.blend_type = "ADD"
                        mix_hm.location = (-120, 220)
                        mix_hm.inputs["B"].default_value = (0.95, 0.96, 1.0, 1.0)
                        nt.links.new(tex_hm.outputs["Color"], sep_hm.inputs["Color"])
                        nt.links.new(sep_hm.outputs["Red"], mul_hm.inputs[0])
                        nt.links.new(mul_hm.outputs["Value"], mix_hm.inputs["Factor"])
                        nt.links.new(tex_d.outputs["Color"], mix_hm.inputs["A"])
                        nt.links.new(mix_hm.outputs["Result"], grp.inputs["BaseColor"])
                    else:
                        mix_hm = nt.nodes.new("ShaderNodeMixRGB")
                        mix_hm.blend_type = "ADD"
                        mix_hm.location = (-120, 220)
                        mix_hm.inputs["Color2"].default_value = (0.95, 0.96, 1.0, 1.0)
                        nt.links.new(tex_hm.outputs["Color"], sep_hm.inputs["Color"])
                        nt.links.new(sep_hm.outputs["Red"], mul_hm.inputs[0])
                        nt.links.new(mul_hm.outputs["Value"], mix_hm.inputs["Fac"])
                        nt.links.new(tex_d.outputs["Color"], mix_hm.inputs["Color1"])
                        nt.links.new(mix_hm.outputs["Color"], grp.inputs["BaseColor"])
                else:
                    nt.links.new(tex_d.outputs["Color"], grp.inputs["BaseColor"])

                if is_fur_shader and (fur_typemask_info is not None or fur_card_tex_info is not None):
                    # Universal Kuro UseFurry shader (fox tail, ear fluff, shoulder fur collar, etc.):
                    # 3-state Vertex Color Alpha (COL0.A) dispatcher when COL0 + UV2 + Fur_Tex + TypeMask exist:
                    #   COL0.A < 0.25         -> Fur Cards: Fur_Tex(UV2).R * FurAlphaIntensity * COL0.R
                    #   0.25 <= COL0.A < 0.75 -> Solid inner core: 1.0 (opaque)
                    #   COL0.A >= 0.75        -> Feathered fur body: clamp(TypeMask(UV0).R * 2.5, 0, 1)
                    fur_alpha_int = max(0.5, min(3.0, float(mi_scalars.get("FurAlphaIntensity", 1.2))))
                    use_vcol_r_fade = float(mi_scalars.get("FurBlendUseVertexRFade", 1.0)) > 0.5

                    transp_fur = nt.nodes.new("ShaderNodeBsdfTransparent")
                    transp_fur.location = (220, -180)
                    mix_fur = nt.nodes.new("ShaderNodeMixShader")
                    mix_fur.location = (380, 0)
                    out_n.location = (560, 0)
                    for lk in list(nt.links):
                        if lk.to_node == out_n and lk.to_socket.name == "Surface":
                            nt.links.remove(lk)
                    nt.links.new(transp_fur.outputs["BSDF"], mix_fur.inputs[1])
                    nt.links.new(grp.outputs["Shader"], mix_fur.inputs[2])
                    nt.links.new(mix_fur.outputs["Shader"], out_n.inputs["Surface"])

                    if vcol_layer_name and fur_uv_name and fur_card_tex_info is not None and fur_typemask_info is not None:
                        # Full 3-state COL0.A dispatch
                        n_uv2 = nt.nodes.new("ShaderNodeUVMap")
                        n_uv2.uv_map = fur_uv_name
                        n_uv2.location = (-720, -680)

                        img_fur = _load_image_once(fur_card_tex_info["disk_path"], "Non-Color", "CHANNEL_PACKED")
                        tex_fur = nt.nodes.new("ShaderNodeTexImage")
                        tex_fur.image = img_fur
                        tex_fur.label = "Fur Card Atlas (Fur_Tex @ UV2)"
                        tex_fur.location = (-500, -680)
                        nt.links.new(n_uv2.outputs["UV"], tex_fur.inputs["Vector"])

                        sep_fur = nt.nodes.new("ShaderNodeSeparateColor")
                        sep_fur.location = (-240, -680)
                        nt.links.new(tex_fur.outputs["Color"], sep_fur.inputs["Color"])

                        n_vc = nt.nodes.new("ShaderNodeVertexColor")
                        n_vc.layer_name = vcol_layer_name
                        n_vc.location = (-500, -960)
                        sep_vc = nt.nodes.new("ShaderNodeSeparateColor")
                        sep_vc.location = (-240, -960)
                        nt.links.new(n_vc.outputs["Color"], sep_vc.inputs["Color"])

                        fur_mul = nt.nodes.new("ShaderNodeMath")
                        fur_mul.operation = "MULTIPLY"
                        fur_mul.use_clamp = True
                        fur_mul.inputs[1].default_value = fur_alpha_int
                        fur_mul.location = (-60, -680)
                        nt.links.new(sep_fur.outputs["Red"], fur_mul.inputs[0])

                        card_alpha_out = fur_mul.outputs["Value"]
                        if use_vcol_r_fade:
                            card_fade = nt.nodes.new("ShaderNodeMath")
                            card_fade.operation = "MULTIPLY"
                            card_fade.use_clamp = True
                            card_fade.location = (100, -740)
                            nt.links.new(fur_mul.outputs["Value"], card_fade.inputs[0])
                            nt.links.new(sep_vc.outputs["Red"], card_fade.inputs[1])
                            card_alpha_out = card_fade.outputs["Value"]

                        img_id = _load_image_once(fur_typemask_info["disk_path"], "Non-Color", "CHANNEL_PACKED")
                        tex_id = nt.nodes.new("ShaderNodeTexImage")
                        tex_id.image = img_id
                        tex_id.label = "Fur Body Mask (TypeMask.R @ UV0)"
                        tex_id.location = (-500, -420)
                        sep_id = nt.nodes.new("ShaderNodeSeparateColor")
                        sep_id.location = (-240, -420)
                        norm_r = nt.nodes.new("ShaderNodeMath")
                        norm_r.operation = "MULTIPLY"
                        norm_r.use_clamp = True
                        norm_r.inputs[1].default_value = 2.5
                        norm_r.location = (-60, -420)
                        nt.links.new(tex_id.outputs["Color"], sep_id.inputs["Color"])
                        nt.links.new(sep_id.outputs["Red"], norm_r.inputs[0])

                        gt_card = nt.nodes.new("ShaderNodeMath")
                        gt_card.operation = "GREATER_THAN"
                        gt_card.inputs[1].default_value = 0.25
                        gt_card.location = (-60, -960)
                        nt.links.new(n_vc.outputs["Alpha"], gt_card.inputs[0])

                        gt_tail = nt.nodes.new("ShaderNodeMath")
                        gt_tail.operation = "GREATER_THAN"
                        gt_tail.inputs[1].default_value = 0.75
                        gt_tail.location = (-60, -1120)
                        nt.links.new(n_vc.outputs["Alpha"], gt_tail.inputs[0])

                        mix_solid_tail = nt.nodes.new("ShaderNodeMix")
                        mix_solid_tail.data_type = "FLOAT"
                        mix_solid_tail.inputs["A"].default_value = 1.0
                        mix_solid_tail.location = (120, -520)
                        nt.links.new(gt_tail.outputs["Value"], mix_solid_tail.inputs["Factor"])
                        nt.links.new(norm_r.outputs["Value"], mix_solid_tail.inputs["B"])

                        mix_final_a = nt.nodes.new("ShaderNodeMix")
                        mix_final_a.data_type = "FLOAT"
                        mix_final_a.location = (260, -520)
                        nt.links.new(gt_card.outputs["Value"], mix_final_a.inputs["Factor"])
                        nt.links.new(card_alpha_out, mix_final_a.inputs["A"])
                        nt.links.new(mix_solid_tail.outputs["Result"], mix_final_a.inputs["B"])

                        nt.links.new(mix_final_a.outputs["Result"], mix_fur.inputs["Fac"])
                        alpha_mode_used = "fur_3state_col0a_feathered"
                        effective_alpha_enabled = True
                    elif fur_typemask_info is not None:
                        img_id = _load_image_once(fur_typemask_info["disk_path"], "Non-Color", "CHANNEL_PACKED")
                        tex_id = nt.nodes.new("ShaderNodeTexImage")
                        tex_id.image = img_id
                        tex_id.label = "Fur Opacity Mask (TypeMask.R)"
                        tex_id.location = (-360, -420)
                        sep_id = nt.nodes.new("ShaderNodeSeparateColor")
                        sep_id.location = (-120, -420)
                        norm_r = nt.nodes.new("ShaderNodeMath")
                        norm_r.operation = "MULTIPLY"
                        norm_r.use_clamp = True
                        norm_r.inputs[1].default_value = 2.5
                        norm_r.location = (60, -420)
                        nt.links.new(tex_id.outputs["Color"], sep_id.inputs["Color"])
                        nt.links.new(sep_id.outputs["Red"], norm_r.inputs[0])
                        nt.links.new(norm_r.outputs["Value"], mix_fur.inputs["Fac"])
                        alpha_mode_used = "fur_typemask_feathered"
                        effective_alpha_enabled = True
                    elif fur_card_tex_info is not None:
                        img_fur = _load_image_once(fur_card_tex_info["disk_path"], "Non-Color", "CHANNEL_PACKED")
                        tex_fur = nt.nodes.new("ShaderNodeTexImage")
                        tex_fur.image = img_fur
                        tex_fur.label = "Fur Card Atlas (Fur_Tex)"
                        tex_fur.location = (-360, -420)
                        if fur_uv_name:
                            n_uv2 = nt.nodes.new("ShaderNodeUVMap")
                            n_uv2.uv_map = fur_uv_name
                            n_uv2.location = (-580, -420)
                            nt.links.new(n_uv2.outputs["UV"], tex_fur.inputs["Vector"])
                        sep_fur = nt.nodes.new("ShaderNodeSeparateColor")
                        sep_fur.location = (-120, -420)
                        norm_f = nt.nodes.new("ShaderNodeMath")
                        norm_f.operation = "MULTIPLY"
                        norm_f.use_clamp = True
                        norm_f.inputs[1].default_value = fur_alpha_int
                        norm_f.location = (60, -420)
                        nt.links.new(tex_fur.outputs["Color"], sep_fur.inputs["Color"])
                        nt.links.new(sep_fur.outputs["Red"], norm_f.inputs[0])
                        nt.links.new(norm_f.outputs["Value"], mix_fur.inputs["Fac"])
                        alpha_mode_used = "fur_tex_feathered"
                        effective_alpha_enabled = True
                elif is_hair_masked:
                    # Universal Kuro Data-Alpha Guard (ISS-002 + ISS-006):
                    # In MSM_ToonCommon, BlendMode=1 is often set solely for camera-proximity dither fade
                    # while MainTex.Alpha stores toon shadow/emissive data (~0.00..0.41, with optional <2% 1.0
                    # emissive sparkles like Down_D: p99=0.404, near_one=0.23%). Only clip when MainTex.Alpha
                    # is genuinely a cutout opacity mask (p99 > 0.55 AND near_one >= 5% AND near_zero >= 1%).
                    pa = base_tex_info.get("pixel_audit") or {}
                    ap = pa.get("alpha_profile") or {}
                    a_sem = str(pa.get("alpha_semantics", ""))
                    a_p99 = float(ap.get("p99", ap.get("max", 1.0)))
                    a_near_one = float(ap.get("near_one_pct", 100.0))
                    a_near_zero = float(ap.get("near_zero_pct", 0.0))
                    a_mid_05_45 = float(ap.get("mid_05_45_pct", 0.0))

                    is_kuro_data_alpha = (
                        a_sem == "data_channel_shadow_mask"
                        or a_p99 <= 0.55
                        or (a_near_one < 5.0 and a_mid_05_45 > 30.0)
                    )
                    if is_kuro_data_alpha:
                        grp.inputs["UseAlphaClip"].default_value = 0.0
                        alpha_mode_used = "opaque_data_alpha_guarded"
                    elif a_near_zero >= 1.0 and a_near_one >= 5.0:
                        grp.inputs["UseAlphaClip"].default_value = 1.0
                        nt.links.new(tex_d.outputs["Alpha"], grp.inputs["Alpha"])
                        alpha_mode_used = "standard_alpha_clip"
                        effective_alpha_enabled = True
                    else:
                        grp.inputs["UseAlphaClip"].default_value = 0.0
                        alpha_mode_used = "opaque_full_alpha"
            else:
                unmatched_slots.append(mat.name)

            # Configure Blender 4.2+/5.x EEVEE render method vs 3.6/4.1 blend_method based on effective alpha
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "DITHERED"
            elif hasattr(mat, "blend_method"):
                mat.blend_method = "CLIP" if effective_alpha_enabled else "OPAQUE"

            if normal_tex_info and "face" not in mat_base.lower() and "eye" not in mat_base.lower():
                img_n = _load_image_once(normal_tex_info["disk_path"], "Non-Color", "CHANNEL_PACKED")
                tex_n = nt.nodes.new("ShaderNodeTexImage")
                tex_n.image = img_n
                tex_n.label = "Normal (_N)"
                tex_n.location = (-360, -140)
                nt.links.new(tex_n.outputs["Color"], grp.inputs["NormalColor"])
                grp.inputs["UseNormal"].default_value = 1.0

            if switch_tex_info:
                img_sw = _load_image_once(switch_tex_info["disk_path"], "sRGB", "CHANNEL_PACKED")
                tex_sw = nt.nodes.new("ShaderNodeTexImage")
                tex_sw.image = img_sw
                tex_sw.label = "Backup _Switch_ Variant (Parked)"
                tex_sw.location = (-360, -1180)

            bound_report.append(
                {
                    "mesh": obj.name,
                    "material": mat.name,
                    "matched_mi": mi["material_name"] if mi else None,
                    "base_color": base_tex_info["name"] if base_tex_info else None,
                    "normal": normal_tex_info["name"] if normal_tex_info else None,
                    "hair_mask": hair_mask_tex_info["name"] if hair_mask_tex_info else None,
                    "fur_mask": fur_typemask_info["name"] if fur_typemask_info else None,
                    "fur_card_atlas": fur_card_tex_info["name"] if fur_card_tex_info else None,
                    "alpha_clip_enabled": effective_alpha_enabled,
                    "alpha_mode": alpha_mode_used,
                }
            )

    return {"bound_slots": bound_report, "unmatched_slots": unmatched_slots}


# ============================================================================
# Smooth-Normal UV Scanner & Skeleton Hierarchy Hash
# ============================================================================

def detect_smooth_normal_uv(mesh_obj) -> Dict[str, Any]:
    """Scan UV1..UV3 for octahedral-encoded smooth normals in [0, 1] used for anime outlines."""
    me = mesh_obj.data
    uv_names = [uv.name for uv in me.uv_layers]
    candidate_index = None
    uv_stats = []

    for idx, uv_layer in enumerate(me.uv_layers):
        n = len(uv_layer.data)
        if n == 0:
            continue
        step = max(1, n // 2000)
        us = [uv_layer.data[i].uv[0] for i in range(0, n, step)]
        vs = [uv_layer.data[i].uv[1] for i in range(0, n, step)]
        in_unit = sum(1 for u, v in zip(us, vs) if -0.02 <= u <= 1.02 and -0.02 <= v <= 1.02) / max(1, len(us))
        u_span = max(us) - min(us)
        v_span = max(vs) - min(vs)
        uv_stats.append(
            {
                "index": idx,
                "name": uv_layer.name,
                "in_unit_ratio": round(in_unit, 3),
                "u_span": round(u_span, 3),
                "v_span": round(v_span, 3),
            }
        )
        # Octahedral smooth normals typically reside in UV1 or UV2, densely covering [0, 1]
        if idx >= 1 and in_unit > 0.95 and u_span > 0.2 and v_span > 0.2 and candidate_index is None:
            candidate_index = idx

    return {
        "uv_count": len(uv_names),
        "uv_names": uv_names,
        "smooth_normal_uv_index": candidate_index if candidate_index is not None else (1 if len(uv_names) > 1 else 0),
        "uv_stats": uv_stats,
    }


def skeleton_hierarchy_hash(armature) -> Tuple[str, List[str], int]:
    pairs = sorted((b.name, b.parent.name if b.parent else "<ROOT>") for b in armature.data.bones)
    roots = [b.name for b in armature.data.bones if b.parent is None]
    raw = "\n".join(f"{n}:{p}" for n, p in pairs).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), roots, len(pairs)


# ============================================================================
# Motion Verification & Studio Preview Rendering
# ============================================================================

def compute_world_bounds(mesh_objs: List[Any]) -> Tuple[Vector, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for obj in mesh_objs:
        ev = obj.evaluated_get(depsgraph)
        for corner in ev.bound_box:
            wc = ev.matrix_world @ Vector(corner)
            mins.x = min(mins.x, wc.x)
            mins.y = min(mins.y, wc.y)
            mins.z = min(mins.z, wc.z)
            maxs.x = max(maxs.x, wc.x)
            maxs.y = max(maxs.y, wc.y)
            maxs.z = max(maxs.z, wc.z)
    if mins.x > 1e8:
        return Vector((-0.5, -0.5, 0.0)), Vector((0.5, 0.5, 1.7))
    return mins, maxs


def measure_motion_delta(armature, frames: List[int]) -> Dict[str, Any]:
    """Measure real skeletal pose deltas across sampled frames to verify character actually moves."""
    if not armature or len(frames) < 2:
        return {"animated": False, "max_bone_pos_delta_m": 0.0, "max_bone_rot_delta_deg": 0.0}

    snapshots: List[Dict[str, Tuple[Vector, Any]]] = []
    for fr in frames:
        bpy.context.scene.frame_set(fr)
        bpy.context.view_layer.update()
        snap = {}
        for pb in armature.pose.bones:
            mat = armature.matrix_world @ pb.matrix
            snap[pb.name] = (mat.to_translation().copy(), mat.to_quaternion().copy())
        snapshots.append(snap)

    max_pos = 0.0
    max_rot = 0.0
    max_bone = ""
    base = snapshots[0]
    for s in snapshots[1:]:
        for bname, (pos0, q0) in base.items():
            pos1, q1 = s[bname]
            dp = (pos1 - pos0).length
            dr = math.degrees(q0.rotation_difference(q1).angle)
            if dp > max_pos:
                max_pos = dp
                max_bone = bname
            if dr > max_rot:
                max_rot = dr

    return {
        "animated": max_rot > 2.0 or max_pos > 0.015,
        "frames_sampled": frames,
        "max_bone_pos_delta_m": round(max_pos, 4),
        "max_bone_rot_delta_deg": round(max_rot, 2),
        "most_active_bone": max_bone,
    }


def setup_studio_and_render(mesh_objs: List[Any], armature, preview_dir: Path, sample_frames: Dict[str, int]) -> List[Dict[str, Any]]:
    """Create studio lighting + auto-framed cameras and render verification previews."""
    preview_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene

    # Pick available EEVEE engine across Blender 3.6 / 4.2 / 5.x
    engines = [e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items]
    if "BLENDER_EEVEE" in engines:
        scene.render.engine = "BLENDER_EEVEE"
    elif "BLENDER_EEVEE_NEXT" in engines:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        scene.render.engine = "CYCLES"

    scene.render.resolution_x = 768
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"

    # Soft dark-slate studio background so both white and dark costumes read clearly
    if scene.world is None:
        scene.world = bpy.data.worlds.new("WW_Studio_World")
    scene.world.use_nodes = True
    bg = next((n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs["Color"].default_value = (0.11, 0.12, 0.16, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    # Key light
    light_data = bpy.data.lights.new("WW_Key_Sun", type="SUN")
    light_data.energy = 2.5
    light_obj = bpy.data.objects.new("WW_Key_Sun", light_data)
    scene.collection.objects.link(light_obj)
    light_obj.rotation_euler = (math.radians(52), math.radians(15), math.radians(-28))

    cam_data = bpy.data.cameras.new("WW_Showcase_Camera")
    cam_data.lens = 50.0
    cam_obj = bpy.data.objects.new("WW_Showcase_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    def _aim_camera(cam_pos: Vector, target: Vector, lens: float = 50.0):
        cam_data.lens = lens
        cam_obj.location = cam_pos
        direction = target - cam_pos
        cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Determine facing direction from head/eye bones or bounding box (UEFormat imports characters facing +Y or -Y)
    # Check nose/eye bone forward vector if present; default front is -Y looking towards +Y, or +Y looking towards -Y
    front_sign = -1.0
    if armature:
        head = armature.pose.bones.get("Bip001Head")
        eye_l = armature.pose.bones.get("Eye_L") or armature.pose.bones.get("Bone_Eye_L")
        if head and eye_l:
            h_pos = armature.matrix_world @ head.head
            e_pos = armature.matrix_world @ eye_l.head
            if (e_pos.y - h_pos.y) > 0:
                front_sign = 1.0

    rendered: List[Dict[str, Any]] = []
    for shot_name, fr in sample_frames.items():
        scene.frame_set(fr)
        bpy.context.view_layer.update()
        bmin, bmax = compute_world_bounds(mesh_objs)
        center = (bmin + bmax) * 0.5
        height = max(0.5, bmax.z - bmin.z)

        if "face" in shot_name:
            head_target = Vector((center.x, center.y, bmin.z + height * 0.86))
            if armature:
                head_pb = armature.pose.bones.get("Bip001Head") or armature.pose.bones.get("Head")
                if head_pb is not None:
                    h_world = armature.matrix_world @ ((head_pb.head + head_pb.tail) * 0.5)
                    head_target = Vector((h_world.x, h_world.y, h_world.z + 0.01))
            dist = height * 0.52
            _aim_camera(Vector((head_target.x + 0.03, head_target.y + front_sign * dist, head_target.z + 0.01)), head_target, lens=78.0)
        elif "action" in shot_name:
            target = Vector((center.x, center.y, bmin.z + height * 0.52))
            dist = height * 1.95
            _aim_camera(Vector((center.x + dist * 0.42, center.y + front_sign * dist * 0.90, target.z + 0.08)), target, lens=50.0)
        else:
            target = Vector((center.x, center.y, bmin.z + height * 0.52))
            dist = height * 1.85
            _aim_camera(Vector((center.x, center.y + front_sign * dist, target.z + 0.06)), target, lens=50.0)

        out_png = preview_dir / f"{shot_name}.png"
        scene.render.filepath = str(out_png)
        bpy.ops.render.render(write_still=True)

        # Quick non-blank render check using Blender image pixels
        is_valid_render = out_png.is_file() and out_png.stat().st_size > 2000
        pixel_std = 0.0
        if is_valid_render:
            try:
                import numpy as np

                rimg = bpy.data.images.load(str(out_png), check_existing=False)
                rw, rh = rimg.size
                buf = np.empty(rw * rh * 4, dtype=np.float32)
                rimg.pixels.foreach_get(buf)
                rgb = buf.reshape(-1, 4)[:, :3]
                pixel_std = float(rgb.std())
                bpy.data.images.remove(rimg)
                if pixel_std < 0.015:
                    is_valid_render = False
            except Exception:
                pass

        rendered.append(
            {
                "shot": shot_name,
                "frame": fr,
                "path": str(out_png.resolve()),
                "bytes": out_png.stat().st_size if out_png.is_file() else 0,
                "pixel_std": round(pixel_std, 4),
                "non_blank_ok": is_valid_render,
            }
        )

    return rendered


def configure_showcase_viewports(mesh_objs: List[Any], armature) -> Dict[str, Any]:
    """Frame all 3D viewports closely on the character in Material Preview and set Animation Dope Sheet to Action Editor.

    Runs right before saving `<ModelId>_showcase.blend` so double-clicking the file immediately shows
    the full character front-and-center in crisp toon shading rather than Blender's default 15m cube view.
    """
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    bmin, bmax = compute_world_bounds(mesh_objs)
    center = (bmin + bmax) * 0.5
    height = max(0.5, bmax.z - bmin.z)
    target = Vector((center.x, center.y, bmin.z + height * 0.52))

    front_sign = -1.0
    if armature:
        head = armature.pose.bones.get("Bip001Head")
        eye_l = armature.pose.bones.get("Eye_L") or armature.pose.bones.get("Bone_Eye_L")
        if head and eye_l:
            h_pos = armature.matrix_world @ head.head
            e_pos = armature.matrix_world @ eye_l.head
            if (e_pos.y - h_pos.y) > 0:
                front_sign = 1.0

    # Reset WW_Showcase_Camera from face-closeup render back to full-body front framing
    cam_obj = scene.camera
    if cam_obj and cam_obj.type == "CAMERA":
        cam_obj.data.lens = 50.0
        cam_dist = height * 1.90
        cam_pos = Vector((center.x, center.y + front_sign * cam_dist, target.z + 0.05))
        cam_obj.location = cam_pos
        cam_obj.rotation_euler = (target - cam_pos).to_track_quat("-Z", "Y").to_euler()

    # Interactive 3D viewport close-up framing (slight front-3/4 angle so character fills viewport cleanly)
    vp_dist = max(1.6, height * 1.95)
    vp_offset = Vector((vp_dist * 0.24, front_sign * vp_dist * 0.96, height * 0.06))
    vp_rot = (-vp_offset).to_track_quat("-Z", "Y")

    view3d_configured = 0
    camera_views_configured = 0
    action_editors_configured = 0

    for ws in bpy.data.workspaces:
        for scr in ws.screens:
            for area in scr.areas:
                if area.type == "VIEW_3D":
                    space = area.spaces.active
                    if space is None:
                        continue
                    try:
                        space.clip_start = 0.01
                        space.clip_end = 1000.0
                    except Exception:
                        pass
                    try:
                        space.shading.type = "MATERIAL"
                    except Exception:
                        pass
                    try:
                        # Keep viewport unobstructed on open; user presses N anytime to open WW Showcase sidebar
                        space.show_region_ui = False
                    except Exception:
                        pass
                    r3d = getattr(space, "region_3d", None)
                    if r3d is not None:
                        try:
                            if r3d.view_perspective == "CAMERA":
                                r3d.view_camera_zoom = 0.0
                                r3d.view_camera_offset = (0.0, 0.0)
                                camera_views_configured += 1
                            else:
                                r3d.view_perspective = "PERSP"
                                r3d.view_location = target
                                r3d.view_distance = vp_dist
                                r3d.view_rotation = vp_rot
                            view3d_configured += 1
                        except Exception:
                            pass
                elif area.type == "DOPESHEET_EDITOR":
                    space = area.spaces.active
                    if space is None:
                        continue
                    try:
                        space.mode = "ACTION"
                        if hasattr(space, "dopesheet") and space.dopesheet is not None:
                            space.dopesheet.show_only_selected = False
                        space.show_region_ui = False
                        action_editors_configured += 1
                    except Exception:
                        pass

    return {
        "character_height_m": round(height, 4),
        "front_sign": front_sign,
        "view_target": [round(target.x, 4), round(target.y, 4), round(target.z, 4)],
        "view_distance_m": round(vp_dist, 4),
        "view3d_configured": view3d_configured,
        "camera_views_configured": camera_views_configured,
        "action_editors_configured": action_editors_configured,
    }


def localize_workspaces_for_host(lang_candidates: List[str]) -> Dict[str, Any]:
    """Localize factory-startup WorkSpace tab names right before saving .blend to match host UI language.

    Runs strictly in-memory inside the isolated headless process (never calls wm.save_userpref),
    renames ONLY `bpy.data.workspaces` via Blender's official `WorkSpace` translation context
    (preserving native tab ordering and leaving all meshes, bones, materials, actions, and FBX untouched),
    and restores preferences.view language immediately afterward.
    """
    candidates = [str(c).strip() for c in (lang_candidates or []) if str(c).strip()]
    ws_before = [w.name for w in bpy.data.workspaces]
    active_before = bpy.context.workspace.name if bpy.context.workspace else None
    if not candidates or candidates[0].lower() in ("en_us", "default"):
        return {
            "requested_candidates": candidates or ["en_US"],
            "applied": False,
            "applied_language": "en_US",
            "renamed_count": 0,
            "renamed_map": {},
            "workspaces": ws_before,
            "active_workspace": active_before,
        }

    view = bpy.context.preferences.view
    avail = set()
    try:
        avail = {it.identifier for it in view.bl_rna.properties["language"].enum_items}
    except Exception:
        avail = set()

    chosen = None
    for cand in candidates:
        if (not avail) or (cand in avail):
            chosen = cand
            break

    if not chosen or chosen.lower() == "en_us":
        return {
            "requested_candidates": candidates,
            "applied": False,
            "applied_language": "en_US",
            "renamed_count": 0,
            "renamed_map": {},
            "workspaces": ws_before,
            "active_workspace": active_before,
        }

    orig_lang = getattr(view, "language", "DEFAULT")
    orig_iface = getattr(view, "use_translate_interface", False)
    orig_data = getattr(view, "use_translate_new_dataname", False)
    renamed: Dict[str, str] = {}
    try:
        view.language = chosen
        if hasattr(view, "use_translate_interface"):
            view.use_translate_interface = True
        if hasattr(view, "use_translate_new_dataname"):
            view.use_translate_new_dataname = True
        for ws in list(bpy.data.workspaces):
            orig_name = ws.name
            try:
                tr_name = bpy.app.translations.pgettext_data(orig_name, "WorkSpace")
            except Exception:
                tr_name = orig_name
            if tr_name and tr_name != orig_name and tr_name not in bpy.data.workspaces:
                ws.name = tr_name
                renamed[orig_name] = ws.name
    except Exception as exc:
        return {
            "requested_candidates": candidates,
            "applied": False,
            "applied_language": orig_lang,
            "renamed_count": len(renamed),
            "renamed_map": renamed,
            "workspaces": [w.name for w in bpy.data.workspaces],
            "active_workspace": bpy.context.workspace.name if bpy.context.workspace else None,
            "warning": str(exc),
        }
    finally:
        try:
            view.language = orig_lang
            if hasattr(view, "use_translate_interface"):
                view.use_translate_interface = orig_iface
            if hasattr(view, "use_translate_new_dataname"):
                view.use_translate_new_dataname = orig_data
        except Exception:
            pass

    return {
        "requested_candidates": candidates,
        "applied": len(renamed) > 0,
        "applied_language": chosen,
        "renamed_count": len(renamed),
        "renamed_map": renamed,
        "workspaces": [w.name for w in bpy.data.workspaces],
        "active_workspace": bpy.context.workspace.name if bpy.context.workspace else None,
    }


# ============================================================================
# Main Entrypoint
# ============================================================================

def main() -> None:
    argv = sys.argv
    sep_idx = argv.index("--")
    job_path = Path(argv[sep_idx + 1])
    result_path = Path(argv[sep_idx + 2])

    job = json.loads(job_path.read_text(encoding="utf-8"))
    out: Dict[str, Any] = {
        "ok": False,
        "blender_version": list(bpy.app.version),
        "errors": [],
        "warnings": [],
    }

    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if hasattr(bpy.utils, "refresh_script_paths"):
            bpy.utils.refresh_script_paths()
        try:
            bpy.ops.extensions.repo_sync_all()
        except Exception:
            pass

        # Enable UEFormat in isolated sandbox
        uef_ok = False
        for cand in (job.get("ueformat_module", ""), "bl_ext.user_default.io_scene_ueformat", "io_scene_ueformat"):
            if not cand:
                continue
            try:
                mod = addon_utils.enable(cand, default_set=True, persistent=False)
                if mod is not None and "import_uemodel" in dir(bpy.ops.uf):
                    uef_ok = True
                    out["ueformat_module"] = cand
                    break
            except Exception:
                pass
        if not uef_ok:
            raise RuntimeError("Failed to enable UEFormat inside sandboxed Blender.")

        # Set UF import settings: scale=0.01 (UE cm -> Blender m), preserve morph targets & sockets.
        # IMPORTANT: Keep import_curves=False because UEFormat 0.10.0 uses a substring matcher that falsely
        # binds locomotion curves (e.g. Weight_Gait, Foot_IK_l) onto single-letter vowel shape keys A/E/I/O!
        # Our own exact case-insensitive v10 curve importer (`read_ueanim_curves` + `apply_shape_key_curves`) handles facial curves cleanly.
        uf_settings = getattr(bpy.context.scene, "uf_settings", None)
        if uf_settings is not None:
            uf_settings.scale_factor = 0.01
            uf_settings.import_morph_targets = True
            uf_settings.import_sockets = True
            uf_settings.target_lod = 0
            if hasattr(uf_settings, "import_curves"):
                uf_settings.import_curves = False

        # 1. Import primary .uemodel meshes (skip sibling alt-form variants so they never stack/clip on top!)
        uemodel_paths = job.get("uemodel_paths", [])
        variant_uemodel_paths = job.get("variant_uemodel_paths", [])
        if not uemodel_paths:
            raise RuntimeError("No primary .uemodel files provided in job.")
        out["variant_uemodels_excluded_from_showcase"] = variant_uemodel_paths

        for ump in uemodel_paths:
            um_path = Path(stage_for_blender(ump))
            bpy.ops.uf.import_uemodel(
                directory=str(um_path.parent),
                files=[{"name": um_path.name}],
            )

        armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        mesh_objs = [o for o in bpy.data.objects if o.type == "MESH"]
        if not armatures or not mesh_objs:
            raise RuntimeError(f"Import yielded {len(armatures)} armatures and {len(mesh_objs)} meshes.")

        # Unify multi-part meshes under primary armature if multiple armatures exist
        master_arm = max(armatures, key=lambda a: len(a.data.bones))
        for other_arm in armatures:
            if other_arm is master_arm:
                continue
            for m in mesh_objs:
                if m.parent is other_arm:
                    m.parent = master_arm
                for mod in m.modifiers:
                    if mod.type == "ARMATURE" and mod.object is other_arm:
                        mod.object = master_arm
            bpy.data.objects.remove(other_arm, do_unlink=True)

        # Rename master Armature literally to 'Armature' so Blender FBX exporter eliminates double-root wrapper!
        orig_arm_name = master_arm.name
        master_arm.name = "Armature"

        # Collect pre-animation mesh & skeleton metrics
        skel_hash, root_bones, bone_count = skeleton_hierarchy_hash(master_arm)
        phys_bones = [b.name for b in master_arm.data.bones if b.name.startswith("Bone")]
        total_verts = sum(len(m.data.vertices) for m in mesh_objs)
        total_polys = sum(len(m.data.polygons) for m in mesh_objs)
        shape_keys = []
        for m in mesh_objs:
            if m.data.shape_keys:
                shape_keys.extend([kb.name for kb in m.data.shape_keys.key_blocks if kb.name != "Basis"])
        uv_info = detect_smooth_normal_uv(mesh_objs[0])

        out["geometry"] = {
            "original_armature_name": orig_arm_name,
            "mesh_count": len(mesh_objs),
            "mesh_names": [m.name for m in mesh_objs],
            "total_vertices": total_verts,
            "total_polygons": total_polys,
            "bone_count": bone_count,
            "root_bones": root_bones,
            "physics_bone_count": len(phys_bones),
            "skeleton_hash": skel_hash,
            "shape_key_count": len(shape_keys),
            "shape_key_sample": shape_keys[:30],
            "uv_audit": uv_info,
        }

        # 2. Apply 3-Tier Materials + Wuthering Waves Toon Shader
        audit_data = json.loads(Path(job["texture_audit_path"]).read_text(encoding="utf-8"))
        mat_report = apply_materials_from_audit(mesh_objs, audit_data)
        out["materials"] = mat_report

        # 3. Export clean rest-pose Standardized Handoff FBX BEFORE assigning animations!
        handoff_dir = Path(job["handoff_dir"])
        handoff_dir.mkdir(parents=True, exist_ok=True)
        model_id = job["model_id"]
        fbx_path = handoff_dir / f"{model_id}_ue_handoff.fbx"

        bpy.ops.object.select_all(action="DESELECT")
        master_arm.select_set(True)
        for m in mesh_objs:
            m.select_set(True)
        bpy.context.view_layer.objects.active = master_arm

        # Scale calibration: UEFormat imported at 0.01 (meters). Export FBX with global_scale=1.0,
        # apply_unit_scale=True, bake_space_transform=False, use_mesh_modifiers=False (keeps Morphs!),
        # use_armature_deform_only=False (keeps physics Bone* chains!), add_leaf_bones=False!
        bpy.ops.export_scene.fbx(
            filepath=str(fbx_path),
            use_selection=True,
            object_types={"ARMATURE", "MESH"},
            use_mesh_modifiers=False,
            mesh_smooth_type="FACE",
            add_leaf_bones=False,
            use_armature_deform_only=False,
            primary_bone_axis="Y",
            secondary_bone_axis="X",
            armature_nodetype="NULL",
            bake_anim=False,
            path_mode="COPY",
            embed_textures=False,
        )
        out["handoff_fbx_path"] = str(fbx_path.resolve())

        # 4. Import Real In-Game Animations (.ueanim), Merge RibbonAnim, Import Shape-Key Curves!
        anim_entries = job.get("animations", [])
        body_anims = [a for a in anim_entries if a.get("category") != "RibbonAnim" and a.get("ueanim_path") and os.path.isfile(_win_ext_path(a["ueanim_path"]))]
        ribbon_anims = [a for a in anim_entries if a.get("category") == "RibbonAnim" and a.get("ueanim_path") and os.path.isfile(_win_ext_path(a["ueanim_path"]))]
        ribbon_by_stem = {Path(a["ueanim_path"]).stem.lower(): a for a in ribbon_anims}

        imported_actions: List[Dict[str, Any]] = []
        primary_showcase_action = None
        primary_showcase_frames = (1, 60)

        for a in body_anims:
            ap = a["ueanim_path"]
            aname = a["name"]
            before_acts = set(bpy.data.actions)

            bpy.ops.object.select_all(action="DESELECT")
            master_arm.select_set(True)
            bpy.context.view_layer.objects.active = master_arm
            try:
                ap_path = Path(stage_for_blender(ap))
                bpy.ops.uf.import_ueanim(
                    directory=str(ap_path.parent),
                    files=[{"name": ap_path.name}],
                )
            except Exception as exc:
                out["warnings"].append(f"Failed to import body anim {aname}: {exc}")
                continue

            new_acts = [act for act in bpy.data.actions if act not in before_acts]
            body_act = new_acts[0] if new_acts else (master_arm.animation_data.action if master_arm.animation_data else None)
            if body_act is None:
                continue
            body_act.name = aname
            body_act.use_fake_user = True

            # Check for matching RibbonAnim (e.g. Rib_Stand1_Action01)
            rib_match = ribbon_by_stem.get(f"rib_{aname.lower()}")
            ribbon_merged_curves = 0
            physics_baked_bones = 0

            if rib_match:
                before_rib = set(bpy.data.actions)
                try:
                    rib_path = Path(stage_for_blender(rib_match["ueanim_path"]))
                    bpy.ops.uf.import_ueanim(
                        directory=str(rib_path.parent),
                        files=[{"name": rib_path.name}],
                    )
                    rib_acts = [act for act in bpy.data.actions if act not in before_rib]
                    if rib_acts:
                        rib_act = rib_acts[0]
                        ribbon_merged_curves = merge_ribbon_action_into_body(body_act, rib_act, master_arm)
                        bpy.data.actions.remove(rib_act)
                except Exception as exc:
                    out["warnings"].append(f"RibbonAnim merge failed for {aname}: {exc}")

            if ribbon_merged_curves == 0:
                # Clean stray Bone* keyframes from body anim so physics bones stay clean
                remove_fcurves_matching(body_act, lambda fc: 'pose.bones["Bone' in fc.data_path)

            # Parse and apply v10 .ueanim facial shape key curves across ALL primary meshes with shape keys!
            sk_matched_total = 0
            sk_kf_total = 0
            sk_actions_map: Dict[str, str] = {}
            try:
                curve_data = read_ueanim_curves(ap)
                if curve_data.get("curves"):
                    sk_meshes = [m for m in mesh_objs if m.data.shape_keys]
                    for m_idx, sm in enumerate(sk_meshes):
                        suffix = "" if len(sk_meshes) == 1 else f"_{m_idx}"
                        sk_res = apply_shape_key_curves(sm, curve_data, f"{aname}{suffix}")
                        sk_matched_total += int(sk_res.get("matched_curves", 0))
                        sk_kf_total += int(sk_res.get("inserted_keyframes", 0))
                        if sk_res.get("action_name"):
                            sk_actions_map[sm.name] = sk_res["action_name"]
            except Exception as exc:
                out["warnings"].append(f"Shape-key curve import failed for {aname}: {exc}")

            # Build bone channel groups (ISS-008) & exact keyframe frame range (ISS-009) on body action!
            fr_start, fr_end = configure_action_metadata(body_act, is_shape_key=False)
            if fr_end <= fr_start:
                fr_end = max(fr_start + 1, int(a.get("num_frames", 60)))

            # Assign active action temporarily if physics bake needed on primary showcase
            if primary_showcase_action is None:
                primary_showcase_action = body_act
                primary_showcase_frames = (fr_start, fr_end)

            imported_actions.append(
                {
                    "name": aname,
                    "category": a.get("category"),
                    "action_name": body_act.name,
                    "frame_start": fr_start,
                    "frame_end": fr_end,
                    "fcurve_count": len(get_action_fcurves(body_act)),
                    "ribbon_merged_fcurves": ribbon_merged_curves,
                    "shape_key_curves_matched": sk_matched_total,
                    "shape_key_keyframes": sk_kf_total,
                    "shape_key_action": next(iter(sk_actions_map.values()), None),
                    "shape_key_actions_by_mesh": sk_actions_map,
                    "is_aerial_loop": bool((a.get("bake_status") or {}).get("is_aerial_loop", False)),
                    "blender_showcase_acceptance": bool((a.get("bake_status") or {}).get("blender_showcase_acceptance", True)),
                }
            )

        # Prefer CommonAnim (Stand/Skill/Burst with ribbon/facial curves, non-aerial) as active showcase action!
        if imported_actions:
            def _showcase_score(rec):
                sc = 0
                if rec.get("blender_showcase_acceptance", True):
                    sc += 35
                if rec["category"] == "CommonAnim":
                    sc += 50
                if rec["ribbon_merged_fcurves"] > 0:
                    sc += 40
                if rec["shape_key_curves_matched"] > 0:
                    sc += 30
                if "stand" in rec["name"].lower():
                    sc += 25
                return sc

            best_rec = max(imported_actions, key=_showcase_score)
            primary_showcase_action = bpy.data.actions.get(best_rec["action_name"])
            primary_showcase_frames = (best_rec["frame_start"], best_rec["frame_end"])

            bind_action_with_slot(master_arm, primary_showcase_action)
            sk_map = best_rec.get("shape_key_actions_by_mesh") or {}
            for sm in mesh_objs:
                if sm.data.shape_keys:
                    sk = sm.data.shape_keys
                    # Reset all non-Basis shape keys to 0.0 so previous actions never leave residual facial deformation!
                    for kb in sk.key_blocks:
                        if kb.name != "Basis":
                            kb.value = 0.0
                    sk_act = bpy.data.actions.get(sk_map[sm.name]) if sm.name in sk_map else None
                    bind_action_with_slot(sk, sk_act)

            # If primary showcase had no RibbonAnim, bake zero-twist rest-frame spring physics onto Bone* chains
            if best_rec["ribbon_merged_fcurves"] == 0 and len(phys_bones) > 0:
                baked_cnt = bake_bone_physics_fallback(master_arm, primary_showcase_frames[0], primary_showcase_frames[1])
                best_rec["physics_baked_bones"] = baked_cnt
                configure_action_metadata(primary_showcase_action, is_shape_key=False)

            bpy.context.scene.frame_start = primary_showcase_frames[0]
            bpy.context.scene.frame_end = primary_showcase_frames[1]
            bpy.context.scene.render.fps = 30

        # Final audit: guarantee 100% of curves across ALL Actions belong to channel groups (ISS-008)!
        cg_total_groups = 0
        cg_total_fcs = 0
        cg_grouped_fcs = 0
        for act in bpy.data.actions:
            cstats = ensure_action_channel_groups(act)
            cg_total_groups += cstats["groups"]
            cg_total_fcs += cstats["total_fcurves"]
            cg_grouped_fcs += cstats["grouped_fcurves"]

        # Embed auto-sync script (ISS-009 frame range auto-fit + ISS-005 per-action facial shape key sync + N-Panel!)
        body_action_names = [rec["action_name"] for rec in imported_actions]
        action_sk_map = {
            rec["action_name"]: rec.get("shape_key_actions_by_mesh") or {}
            for rec in imported_actions
        }
        embed_action_sync_script(master_arm, body_action_names, action_sk_map)

        out["animations"] = {
            "imported_count": len(imported_actions),
            "active_showcase_action": primary_showcase_action.name if primary_showcase_action else None,
            "frame_range": list(primary_showcase_frames),
            "ww_action_sync_embedded": True,
            "channel_group_audit": {
                "actions_audited": len(bpy.data.actions),
                "total_groups": cg_total_groups,
                "total_fcurves": cg_total_fcs,
                "grouped_fcurves": cg_grouped_fcs,
                "all_curves_grouped": (cg_total_fcs == cg_grouped_fcs),
            },
            "details": imported_actions,
        }

        # 5. Measure Real Skeletal Motion Across Frames (Verify character actually animates!)
        f0, f1 = primary_showcase_frames
        f_mid = f0 + max(1, (f1 - f0) // 3)
        f_late = f0 + max(2, (2 * (f1 - f0)) // 3)
        motion_check = measure_motion_delta(master_arm, [f0, f_mid, f_late])
        out["motion_verification"] = motion_check

        # 6. Setup Studio Lighting/Camera + Render Multi-Angle / Multi-Frame Previews
        preview_dir = Path(job["preview_dir"])
        renders = setup_studio_and_render(
            mesh_objs,
            master_arm,
            preview_dir,
            {
                "preview_front_start": f0,
                "preview_action_mid": f_mid,
                "preview_face_closeup": f_mid,
            },
        )
        out["renders"] = renders

        # Reset timeline to start frame, clean armature viewport display (ISS-004),
        # organize visual Bone Collections (after FBX export!), select Armature (avoids A1/A2!), and pack textures!
        bpy.context.scene.frame_set(f0)
        master_arm.show_in_front = False
        if hasattr(master_arm.data, "collections"):
            try:
                # Hide any pre-existing auxiliary collections created by UEFormat (e.g. 'Sockets')
                for existing_bc in master_arm.data.collections:
                    existing_bc.is_visible = False
                c_core = master_arm.data.collections.get("Core_Bip001") or master_arm.data.collections.new("Core_Bip001")
                c_phys = master_arm.data.collections.get("Physics_Bone") or master_arm.data.collections.new("Physics_Bone")
                c_props = master_arm.data.collections.get("Props_Other") or master_arm.data.collections.new("Props_Other")
                for b in master_arm.data.bones:
                    bn = b.name
                    if bn == "Root" or bn.startswith("Bip"):
                        c_core.assign(b)
                    elif bn.startswith("Bone"):
                        c_phys.assign(b)
                    else:
                        c_props.assign(b)
                c_core.is_visible = True
                c_phys.is_visible = False
                c_props.is_visible = False
            except Exception as exc:
                out["warnings"].append(f"Bone collection setup skipped: {exc}")

        # Keep Armature active & selected on save so Action Editor & Pose Mode work immediately on open (A1/A2)!
        bpy.ops.object.select_all(action="DESELECT")
        master_arm.select_set(True)
        bpy.context.view_layer.objects.active = master_arm

        try:
            bpy.ops.file.pack_all()
            out["textures_packed_in_blend"] = True
        except Exception as exc:
            out["textures_packed_in_blend"] = False
            out["warnings"].append(f"pack_all warning: {exc}")

        # Frame 3D viewports closely on the character in Material Preview & set Animation editor to Action mode
        out["viewport_framing"] = configure_showcase_viewports(mesh_objs, master_arm)

        # Localize top-bar WorkSpace datablock names right before saving .blend to match host UI language
        # (prevents mixed-language top bar when opened in Chinese/localized Blender with Load UI enabled!).
        out["workspace_localization"] = localize_workspaces_for_host(job.get("ui_language_candidates") or [])

        blend_path = Path(job["blend_out_path"])
        blend_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        out["showcase_blend_path"] = str(blend_path.resolve())

        # 7. Independent Round-Trip FBX Cross-Verification (VerifyGate 2!)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(fbx_path))
        rt_arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        rt_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        rt_verts = sum(len(m.data.vertices) for m in rt_meshes)
        rt_bones = len(rt_arms[0].data.bones) if rt_arms else 0
        rt_roots = [b.name for b in rt_arms[0].data.bones if b.parent is None] if rt_arms else []
        rt_phys = len([b for b in rt_arms[0].data.bones if b.name.startswith("Bone")]) if rt_arms else 0
        rt_sks = sum(
            len([kb for kb in m.data.shape_keys.key_blocks if kb.name != "Basis"])
            for m in rt_meshes
            if m.data.shape_keys
        )
        has_double_root = any(r.lower() == "armature" for r in rt_roots)
        morph_retention = (rt_sks / max(1, len(shape_keys))) if shape_keys else 1.0

        out["fbx_roundtrip_verify"] = {
            "fbx_bytes": fbx_path.stat().st_size if fbx_path.is_file() else 0,
            "mesh_count": len(rt_meshes),
            "vertices": rt_verts,
            "bones": rt_bones,
            "root_bones": rt_roots,
            "has_double_root_armature": has_double_root,
            "physics_bone_count": rt_phys,
            "shape_key_count": rt_sks,
            "morph_retention_ratio": round(morph_retention, 4),
        }

        out["ok"] = True
    except Exception as exc:
        out["errors"].append(str(exc))
        out["traceback"] = traceback.format_exc()
    finally:
        if _SHORT_STAGE_DIR is not None and _SHORT_STAGE_DIR.exists():
            shutil.rmtree(_SHORT_STAGE_DIR, ignore_errors=True)

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("WW_ASSEMBLE_DONE:" + ("OK" if out["ok"] else "FAIL"))


if __name__ == "__main__":
    main()
