#!/usr/bin/env python3
"""客户机自更新器：从"公开更新通道"拉取并更新本产品（纯 stdlib，可被 agent 直接调用）。

安全设计（这是远程代码执行，必须守规矩）：
  · 默认 **dry-run**：只探测+列清单，不动文件；加 --apply 才写
  · 多通道兜底：jsDelivr → raw.githubusercontent → gh-proxy（中国网络下 raw 常被墙）
  · 双层校验：整包 sha256 + 包内 MANIFEST.md5 逐文件 md5，任何不符立即中止
  · 更新前自动备份，失败/不满意可 --rollback 一键回滚
  · 路径白名单：只允许写 plugins/<id>/、desktop-plugins/<id>/、skills/、扩展目录
    **永不动** state/（Seller Key 与业务数据）、永不动 Hermes 本体
  · 全程记账到 state/update_audit.jsonl

用法（客户机）:
  python selfupdate.py --repo <owner>/<repo>                 # 检查更新（不动文件）
  python selfupdate.py --repo <owner>/<repo> --apply         # 应用（先自动备份）
  python selfupdate.py --rollback                            # 回滚到上一个备份
  python selfupdate.py --status                              # 当前版本 + 上一次更新时间
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#: 顺序有讲究：jsDelivr 对 @main 有较长缓存，会把"新版本"压住 → 放最后；
#: raw 的缓存只有几分钟，作为首选；gh-proxy 是 raw 的镜像，同样新鲜。
DEFAULT_CHANNELS = [
    # 1) GitHub Contents API：**没有 CDN 缓存**，发布后立刻可见（匿名 60 次/小时够用）
    "https://api.github.com/repos/{repo}/contents/{path}?ref={ref}",
    # 2) raw：只有几分钟缓存，可靠且快
    "https://raw.githubusercontent.com/{repo}/{ref}/{path}",
    # 3) gh-proxy：raw 的镜像（中国网络）
    "https://gh-proxy.com/https://raw.githubusercontent.com/{repo}/{ref}/{path}",
    # 4) jsDelivr：快，但对 @main 缓存很久（可达数小时）→ 只当兜底
    "https://cdn.jsdelivr.net/gh/{repo}@{ref}/{path}",
]
UA = {"User-Agent": "erp-selfupdate/1.0", "Accept": "*/*"}


# ---------------------------------------------------------------- 路径解析

def hermes_home() -> str:
    """HERMES_HOME 优先且**即使目录还不存在也认**（全新机器/沙箱常见），其余情况才回落默认位置。
    值要先去掉空格与引号：环境变量经常带尾部空格，拼出来的路径会"看着对却找不到"。"""
    v = (os.environ.get("HERMES_HOME") or "").strip().strip('"').strip("'").rstrip("\\/")
    if v:
        os.makedirs(v, exist_ok=True)
        return v
    if os.name == "nt":
        p = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~/.hermes")


def find_plugin_dir(pid: str) -> str:
    for cand in (os.path.join(hermes_home(), "plugins", pid),
                 os.path.join(hermes_home(), "..", "plugins", pid)):
        cand = os.path.abspath(cand)
        if os.path.isdir(cand):
            return cand
    return os.path.abspath(os.path.join(hermes_home(), "plugins", pid))


def state_dir(plugin_dir: str) -> str:
    d = os.path.join(plugin_dir, "state")
    os.makedirs(d, exist_ok=True)
    return d


def installed_path(plugin_dir: str) -> str:
    return os.path.join(state_dir(plugin_dir), "installed.json")


def audit(plugin_dir: str, **row) -> None:
    try:
        row.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        with open(os.path.join(state_dir(plugin_dir), "update_audit.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 下载

def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_first(channels: list, path: str, timeout: int = 30, bust_cache: bool = False):
    """按顺序试每个通道；返回 (bytes, 实际使用的 URL)。

    bust_cache=True 时给 URL 加上一次性查询串：CDN（尤其 jsDelivr 的 @main）缓存很顽固，
    不加的话客户端可能一直读到旧清单、误判"已是最新"。包文件名本身带版本，无需穿透。
    """
    errs = []
    for base in channels:
        if "{path}" in base:
            url = base.format(path=path.lstrip("/"))
        else:
            url = base.rstrip("/") + "/" + path.lstrip("/")
        if bust_cache:
            url += ("&" if "?" in url else "?") + "cb=%d" % int(time.time())
        try:
            data = fetch(url, timeout)
            # GitHub Contents API 返回的是 base64 包装的 JSON
            if "api.github.com" in url:
                meta = json.loads(data.decode("utf-8", "replace"))
                if isinstance(meta, dict) and meta.get("content") and meta.get("encoding") == "base64":
                    import base64
                    data = base64.b64decode(meta["content"])
                elif isinstance(meta, dict) and meta.get("message"):
                    raise RuntimeError("API: %s" % meta["message"])
            return data, url
        except urllib.error.HTTPError as e:
            errs.append("%s → HTTP %d" % (url.split("?")[0], e.code))
        except Exception as e:
            errs.append("%s → %s" % (url.split("?")[0], type(e).__name__))
    raise SystemExit("所有通道都失败：\n  " + "\n  ".join(errs))


# ---------------------------------------------------------------- 白名单映射

def map_member(member: str, delivery_dir: str, cfg: dict) -> str | None:
    """包内路径 → 目标绝对路径；不在白名单内返回 None（跳过）。"""
    pid = cfg["pluginId"]
    extn = cfg["extName"]
    home = hermes_home()
    prefix = delivery_dir + "/"
    if not member.startswith(prefix):
        return None
    rel = member[len(prefix):]
    # 绝不写 state（客户数据）
    if "/state/" in "/" + rel or rel.startswith("state/"):
        return None
    rules = [
        ("payload/hermes-home/plugins/%s/" % pid, os.path.join(home, "plugins", pid)),
        ("payload/hermes-home/desktop-plugins/%s/" % pid, os.path.join(home, "desktop-plugins", pid)),
        ("payload/hermes-home/skills/", os.path.join(home, "skills")),
        ("payload/extension/%s/" % extn, os.path.join(home, extn)),
    ]
    for pre, dst in rules:
        if rel.startswith(pre):
            tail = rel[len(pre):].lstrip("/")
            if not tail:
                return None
            return os.path.join(dst, tail.replace("/", os.sep))
    return None


# ---------------------------------------------------------------- 各动作

def cmd_status(plugin_dir: str) -> int:
    p = installed_path(plugin_dir)
    if not os.path.exists(p):
        print("本地没有更新记录（说明这台是整包安装，或还没更新过）")
        print("插件目录: %s" % plugin_dir)
        return 0
    d = json.load(open(p, encoding="utf-8"))
    print("当前版本 : %s" % d.get("version"))
    print("更新时间 : %s" % d.get("applied_at"))
    print("上次通道 : %s" % d.get("channel"))
    print("备份目录 : %s" % d.get("backup_dir"))
    return 0


def cmd_check(plugin_dir: str, channels: list, cfg: dict, quiet: bool = False) -> dict:
    raw, url = fetch_first(channels, "update.json", bust_cache=True)
    remote = json.loads(raw.decode("utf-8", "replace"))
    print("通道可用 : %s" % url)
    print("远端版本 : %s  (%s)" % (remote.get("version"), remote.get("released_at")))
    if remote.get("notes"):
        print("变更说明 : %s" % remote["notes"])

    local_p = installed_path(plugin_dir)
    local_ver = ""
    if os.path.exists(local_p):
        try:
            local_ver = json.load(open(local_p, encoding="utf-8")).get("version", "")
        except Exception:
            local_ver = ""
    cur = local_ver or "（未知/未记录）"
    print("本机版本 : %s" % cur)
    print("包       : %s  %.2f MB  md5=%s…" % (remote["payload"]["name"],
                                             remote["payload"]["size"] / 1048576,
                                             remote["payload"]["md5"][:12]))
    print("文件数   : %s（逐个 md5 校验）" % remote.get("file_count"))

    same = (remote.get("version") == local_ver and local_ver)
    print()
    if same:
        print("→ 已经是最新，无需更新")
    else:
        print("→ 有更新可装。要装就加 --apply（装前会自动备份，失败可 --rollback）")
    return {"remote": remote, "channels": channels, "up_to_date": bool(same), "local_version": local_ver}


def cmd_apply(plugin_dir: str, info: dict, cfg: dict) -> int:
    remote = info["remote"]
    channels = info["channels"]
    payload = remote["payload"]
    files = remote.get("files") or {}
    ver = remote.get("version", "unknown")

    print()
    print("=== 下载 ===")
    blob, url = fetch_first(channels, payload["name"], timeout=180)
    print("  取到 %.2f MB（%s）" % (len(blob) / 1048576, url))

    import hashlib as _h
    if _h.sha256(blob).hexdigest() != payload["sha256"]:
        audit(plugin_dir, action="apply", version=ver, result="abort", why="sha256 mismatch")
        raise SystemExit("✗ 整包 sha256 不符，已中止（疑似下载损坏或被篡改）")
    if _h.md5(blob).hexdigest() != payload["md5"]:
        audit(plugin_dir, action="apply", version=ver, result="abort", why="md5 mismatch")
        raise SystemExit("✗ 整包 md5 不符，已中止")
    print("  ✓ 整包指纹核对通过")

    zf = zipfile.ZipFile(io.BytesIO(blob))
    bad = zf.testzip()
    if bad:
        raise SystemExit("✗ 压缩包损坏: %s" % bad)

    print()
    print("=== 逐文件校验（包内 MANIFEST）===")
    checked = 0
    mism = []
    for rel, want in files.items():
        # MANIFEST 的键相对 payload/（如 hermes-home/plugins/<id>/tools.py）
        candidates = [remote["delivery_dir"] + "/payload/" + rel, remote["delivery_dir"] + "/" + rel]
        data = None
        for member in candidates:
            try:
                data = zf.read(member)
                break
            except KeyError:
                continue
        if data is None:
            mism.append("%s（包内缺失）" % rel)
            continue
        checked += 1
        if hashlib.md5(data).hexdigest() != want:
            mism.append(rel)
    if mism:
        audit(plugin_dir, action="apply", version=ver, result="abort", why="file md5 mismatch", files=mism[:10])
        raise SystemExit("✗ %d 个文件 md5 不符，已中止：%s" % (len(mism), mism[:5]))
    print("  ✓ %d 个文件全部核对通过" % checked)

    # 计划
    plan = []
    for member in zf.namelist():
        if member.endswith("/"):
            continue
        dst = map_member(member, remote["delivery_dir"], cfg)
        if dst:
            plan.append((member, dst))
    print()
    print("=== 将写入 %d 个文件（白名单内；不含任何 state/ 与 Hermes 本体）===" % len(plan))
    for member, dst in plan[:12]:
        print("  %s" % os.path.relpath(dst, hermes_home()))
    if len(plan) > 12:
        print("  … 其余 %d 个" % (len(plan) - 12))

    # 备份
    backup = os.path.join(state_dir(plugin_dir), "_backup", ver + "-" + time.strftime("%Y%m%d%H%M%S"))
    os.makedirs(backup, exist_ok=True)
    # 版本记录也要进备份：否则回滚后机器仍以为自己在"新版"，会把后续更新跳过
    _ip = installed_path(plugin_dir)
    if os.path.exists(_ip):
        shutil.copy2(_ip, os.path.join(backup, "_installed.json"))
    n_bak = 0
    for _member, dst in plan:
        if os.path.exists(dst):
            rel = os.path.relpath(dst, hermes_home())
            tgt = os.path.join(backup, rel)
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            shutil.copy2(dst, tgt)
            n_bak += 1
    print()
    print("=== 备份 %d 个将被覆盖的文件 → %s ===" % (n_bak, bracket(backup, 90)))

    # 落盘
    for member, dst in plan:
        data = zf.read(member)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
    print("=== 已写入 %d 个文件 ===" % len(plan))

    # 记录
    rec = {
        "version": ver, "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "channel": remote.get("channel", ""),
        "backup_dir": backup, "files": {rel: files[rel] for rel in files}, "payload_md5": payload["md5"],
    }
    open(installed_path(plugin_dir), "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False, indent=2))
    audit(plugin_dir, action="apply", version=ver, result="ok", files=len(plan), backup=backup)
    print()
    print("完成。当前版本 → %s" % ver)
    print("提示：界面半边(plugin.js) 由桌面 App 热加载；浏览器扩展若更新了，请在 chrome://extensions 点一次「重新加载」。")
    print("      建议接着跑 selfcheck.ps1 自检（应 9/9 PASS）。")
    return 0


def bracket(s: str, n: int) -> str:
    return s if len(s) <= n else "…" + s[-n:]


def cmd_rollback(plugin_dir: str) -> int:
    root = os.path.join(state_dir(plugin_dir), "_backup")
    if not os.path.isdir(root):
        raise SystemExit("没有备份可回滚（%s 不存在）" % root)
    cands = sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])
    if not cands:
        raise SystemExit("备份目录为空")
    latest = os.path.join(root, cands[-1])
    print("从备份回滚: %s" % latest)
    home = hermes_home()
    n = 0
    for dirpath, _dirs, fs in os.walk(latest):
        for f in fs:
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(src, latest)
            dst = os.path.join(home, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    _snap = os.path.join(latest, "_installed.json")
    if os.path.exists(_snap):
        shutil.copy2(_snap, installed_path(plugin_dir))
        try:
            prev_ver = json.load(open(_snap, encoding="utf-8")).get("version")
        except Exception:
            prev_ver = "?"
        print("版本记录已回滚 → %s" % prev_ver)
    else:
        try:
            os.remove(installed_path(plugin_dir))
            print("没有旧版本记录快照，已清除本地版本记录（下次会当作未记录）")
        except Exception:
            pass
    audit(plugin_dir, action="rollback", result="ok", files=n, from_backup=latest)
    print("已恢复 %d 个文件到更新前状态。" % n)
    print("（state/ 里的 Seller Key 与业务数据全程未被动过。）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("ERP_UPDATE_REPO", ""),
                    help="公开通道仓库 owner/repo，如 liuyuhan180661-cell/takealot-erp-updates")
    ap.add_argument("--ref", default=os.environ.get("ERP_UPDATE_REF", "main"))
    ap.add_argument("--channel", action="append", default=[], help="自定义通道前缀（可多次）")
    ap.add_argument("--config", default=os.environ.get("DELIVERY_CONFIG") or None)
    ap.add_argument("--plugin-dir", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true", help="即使版本相同也重新应用（仍会做全部校验）")
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import delivery_cfg
        cfg = delivery_cfg.load(["--config", args.config] if args.config else [])
    except Exception:
        cfg = {"pluginId": "takealot-erp", "extName": "Takealot-Assistant-Extension",
               "productName": "Takealot", "pkgPrefix": "Takealot-ERP", "deliveryDir": "Takealot-ERP-Delivery"}

    plugin_dir = args.plugin_dir or find_plugin_dir(cfg["pluginId"])
    print("插件目录 : %s" % plugin_dir)

    if args.rollback:
        return cmd_rollback(plugin_dir)
    if args.status:
        return cmd_status(plugin_dir)

    if not args.repo and not args.channel:
        raise SystemExit("需要 --repo owner/repo（或用 ERP_UPDATE_REPO 环境变量），或 --channel <URL前缀>")
    channels = args.channel or [c.format(repo=args.repo, ref=args.ref) for c in DEFAULT_CHANNELS]

    info = cmd_check(plugin_dir, channels, cfg)
    audit(plugin_dir, action="check", remote=info["remote"].get("version"),
          local=info["local_version"], up_to_date=info["up_to_date"])
    if args.apply:
        if info["up_to_date"] and not args.force:
            print("已是最新，跳过（要强制重装当前版本：加 --force）。")
            return 0
        return cmd_apply(plugin_dir, info, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
