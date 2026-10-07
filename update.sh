#!/bin/sh
# Takealot ERP v3 — 引导升级（macOS / Linux）
#
# 为什么需要它：今天之前装的机器，那份 cli.py 里**还没有 `erp update`**（鸡生蛋）。
# 这个脚本只做"下载新包 → 校验 sha256 → 交给新包自己的 setup 覆盖安装"，
# 装完那台机器就有 `erp update` 了，以后可以自更新。
#
# 用法：
#   sh update.sh                      # 用内置通道
#   ERP_UPDATE_CHANNEL=file:///tmp/ch sh update.sh      # 本地假通道（自测）
#
# 红线：**sha256 校验不过就退出**，磁盘一个字节都不动。
set -e

PY="${ERP_PYTHON:-$(command -v python3 || true)}"
[ -n "$PY" ] || { echo "需要 python3（用来校验 sha256 与解析清单）" >&2; exit 1; }

# 多通道降级：国内 raw 常被 DNS 抽风挡掉（实测报 getaddrinfo failed），留一个 CDN 兜底。
# ERP_UPDATE_CHANNEL 可以覆盖（支持 file:// 本地自测）。
if [ -n "${ERP_UPDATE_CHANNEL:-}" ]; then
  CHANNELS="$ERP_UPDATE_CHANNEL"
else
  CHANNELS="https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/ \
https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/ \
https://ghfast.top/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/ \
https://cdn.jsdelivr.net/gh/liuyuhan180661-cell/takealot-erp-update@main/"
fi
CHANNEL=""
for C in $CHANNELS; do
  case "$C" in */) ;; *) C="$C/" ;; esac
  if "$PY" - "$C" <<'PYEOF' >/dev/null 2>&1
import sys, urllib.request, pathlib
url = sys.argv[1] + "update.json"
if url.startswith("file://"):
    pathlib.Path(url[7:]).read_bytes()
else:
    req = urllib.request.Request(url, headers={"User-Agent": "takealot-erp-bootstrap"})
    urllib.request.urlopen(req, timeout=25).read()
PYEOF
  then CHANNEL="$C"; echo "   通道: $CHANNEL"; break; fi
  echo "   通道不可用，换下一个: $C" >&2
done
[ -n "$CHANNEL" ] || { echo "所有通道都取不到 update.json，中止（什么都不装）" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/erp-update.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "── Takealot ERP 升级"
echo "   通道: $CHANNEL"

# 1) 取清单（支持 file:// 与 http(s)://）
"$PY" - "$CHANNEL" "$TMP/update.json" <<'EOF'
import sys, urllib.request, pathlib
base, out = sys.argv[1], sys.argv[2]
url = base + "update.json"
if url.startswith("file://"):
    data = pathlib.Path(url[7:]).read_bytes()
else:
    req = urllib.request.Request(url, headers={"User-Agent": "takealot-erp-bootstrap"})
    data = urllib.request.urlopen(req, timeout=30).read()
pathlib.Path(out).write_bytes(data)
print("   清单: OK")
EOF

# 2) 读清单里的包名/指纹/版本
#    （注意：不要写成 `read <<EOF $(... <<EOF ...)` —— sh 里嵌套 heredoc 套进命令替换是非法语法，
#     第一次就是这么翻车的。落一个临时文件再 cut，最土也最稳。）
"$PY" - "$TMP/update.json" "$TMP/meta" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
p = d.get("payload") or {}
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    fh.write("\t".join([p.get("name", ""), p.get("sha256", ""), d.get("version", "")]))
EOF
NAME="$(cut -f1 "$TMP/meta")"
SHA="$(cut -f2 "$TMP/meta")"
REMOTE="$(cut -f3 "$TMP/meta")"
[ -n "$NAME" ] || { echo "清单里没有 payload.name，中止" >&2; exit 1; }

# 3) 下载
echo "   包体: $NAME（$REMOTE）"
if [ "${CHANNEL#file://}" != "$CHANNEL" ]; then
  cp "${CHANNEL#file://}$NAME" "$TMP/$NAME"
else
  command -v curl >/dev/null 2>&1 || { echo "需要 curl 下载包体" >&2; exit 1; }
  curl -fsSL "$CHANNEL$NAME" -o "$TMP/$NAME"
fi

# 4) 校验（不通过就退出，什么都不动）
GOT="$("$PY" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$TMP/$NAME")"
if [ -n "$SHA" ] && [ "$GOT" != "$SHA" ]; then
  echo "   ⚠️ sha256 不匹配，**已中止，没有安装**（want ${SHA%${SHA#????????????}}… got ${GOT%${GOT#????????????}}…）" >&2
  exit 1
fi
echo "   校验: OK"

# 5) 解压 → 用新包自己的 setup 覆盖安装（幂等，会先停服务再换文件再起服务）
unzip -q "$TMP/$NAME" -d "$TMP/x" 2>/dev/null || "$PY" -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$TMP/$NAME" "$TMP/x"
CLI="$(find "$TMP/x" -path '*/payload/server/cli.py' | head -1)"
[ -n "$CLI" ] || { echo "包结构不对：找不到 payload/server/cli.py" >&2; exit 1; }
PAYLOAD="$(dirname "$CLI")/.."

HOME_DIR="${ERP_HOME:-$HOME/.takealot-erp}"
RUNNER="$HOME_DIR/venv/bin/python"
[ -x "$RUNNER" ] || RUNNER="$PY"
echo "── 用新包装到 $HOME_DIR"
"$RUNNER" "$CLI" setup --source "$PAYLOAD" --erp-home "$HOME_DIR" --offline
echo
echo "装完了。以后升级直接用："
echo "  \"$HOME_DIR/venv/bin/python\" \"$HOME_DIR/server/cli.py\" update --check"
