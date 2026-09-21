"""交付配置统一读取（供 refresh_package.py / verify_final_pkg.py / render_release.py 用）。

优先级: 环境变量 > 命令行 --config > 仓库根 delivery.config.json
路径类还可再用环境变量单项覆盖，便于在别的机器/别的客户环境上跑。
"""
from __future__ import annotations

import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _arg_config(argv=None):
    argv = argv if argv is not None else sys.argv
    if "--config" in argv:
        i = argv.index("--config")
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def load(argv=None) -> dict:
    path = os.environ.get("DELIVERY_CONFIG") or _arg_config(argv) or os.path.join(ROOT_DIR, "delivery.config.json")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["_config_path"] = path
    cfg["_root"] = ROOT_DIR
    # 派生值
    cfg["pluginIdUs"] = cfg["pluginId"].replace("-", "_")
    cfg["today"] = __import__("datetime").date.today().strftime("%Y%m%d")
    cfg["zipName"] = "%s-交付包-%s.zip" % (cfg["pkgPrefix"], os.environ.get("DELIVERY_TAG") or cfg["today"])
    cfg["outDir"] = cfg.get("outDir") or os.environ.get("DELIVERY_OUT") or os.path.join(ROOT_DIR, "dist")
    cfg["buildDir"] = cfg.get("buildDir") or os.environ.get("DELIVERY_BUILD") or os.path.join(ROOT_DIR, "build")
    return cfg


def _clean(v):
    """环境变量/配置里的路径常带尾部空格或引号（cmd 的 `set X=值 && ...` 就会并入空格），
    不清理会导致"路径看着对、就是找不到"这类最难查的故障。"""
    if not isinstance(v, str):
        return v
    return v.strip().strip('"').strip("'").rstrip("\\") if len(v.strip()) > 3 else v.strip()


def paths(cfg) -> dict:
    """客户机/本机路径：命令行 > 环境变量 > 配置 paths 段。"""
    p = {k: _clean(v) for k, v in (cfg.get("paths") or {}).items()}
    env_map = {
        "stage": "DELIVERY_STAGE", "pluginSrc": "DELIVERY_PLUGIN_SRC", "uiSrc": "DELIVERY_UI_SRC",
        "extSrc": "DELIVERY_EXT_SRC", "skillSrc": "DELIVERY_SKILL_SRC", "zipDir": "DELIVERY_ZIP_DIR",
    }
    for k, env in env_map.items():
        raw = os.environ.get(env)
        if raw:
            p[k] = _clean(raw)
    return p


def expand(value: str, cfg) -> str:
    """把配置里的 {{PID}}/{{DELIVERY_DIR}} 之类的占位展开成实际值。"""
    if not isinstance(value, str):
        return value
    for tok, val in {
        "{{PLUGIN_ID}}": cfg["pluginId"],
        "{{PLUGIN_ID_US}}": cfg["pluginIdUs"],
        "{{PRODUCT_NAME}}": cfg["productName"],
        "{{PRODUCT_SLUG}}": cfg["productSlug"],
        "{{SKILL_ID}}": cfg["skillId"],
        "{{EXT_NAME}}": cfg["extName"],
        "{{PKG_PREFIX}}": cfg["pkgPrefix"],
        "{{DELIVERY_DIR}}": cfg["deliveryDir"],
        "{{DATA_PREFIX}}": cfg["dataPrefix"],
        "{{BRIDGE_PORT}}": str(cfg["bridgePort"]),
        "{{PROXY_ENV}}": cfg["proxyEnvVar"],
    }.items():
        value = value.replace(tok, str(val))
    return value
