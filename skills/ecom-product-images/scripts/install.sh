#!/usr/bin/env bash
# ecom-product-images 依赖安装（只含安装地址与命令，不含任何二进制/凭证）
#
#   bash install.sh                # 基础（本地抠图 + 本地排版 + 本地翻译）
#   bash install.sh --with-isnet   # 额外下 isnet 抠图模型（边缘更细，慢 3 倍）
#
# 幂等：重复跑只补缺的东西。装完打印下一步。
set -uo pipefail

VENV="${IMGTOOLS_VENV:-$HOME/.hermes/venvs/imgtools}"
MODELS="${IMGTOOLS_MODELS:-$HOME/.hermes/venvs/models}"
PY="${PYTHON:-python3}"
IDX="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
MIRRORS=("" "https://gh-proxy.com/" "https://ghproxy.net/")   # 模型下载降级通道（中国大陆）
WITH_ISNET=0
[ "${1:-}" = "--with-isnet" ] && WITH_ISNET=1

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '   \033[33m!\033[0m %s\n' "$*"; }
die() { printf '   \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. venv
say "1/5 准备 venv：$VENV"
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" || die "uv venv 失败"
  else
    "$PY" -m venv "$VENV" || die "python venv 失败（需要 python3.9+）"
  fi
fi
PYBIN="$VENV/bin/python"
ok "$($PYBIN -V 2>&1)"

pip_install() {  # pip_install <pip 参数...>
  if command -v uv >/dev/null 2>&1; then uv pip install --python "$PYBIN" "$@"
  else "$PYBIN" -m pip install --index-url "$IDX" "$@"; fi
}

# ---------------------------------------------------------------- 2. 基础包
say "2/5 基础包（Pillow 排版 + onnxruntime 推理）"
pip_install pillow numpy onnxruntime || die "基础包安装失败"

# ---------------------------------------------------------------- 3. OCR（本地翻译用）
# 坑：opencv 新版只发 macOS 13+ 的 wheel，老 macOS 会掉进源码编译（卡十几分钟）。
#     4.9.0.80 是 numpy1 编译的，必须配 numpy<2，否则 cv2 报 _ARRAY_API not found。
say "3/5 OCR 依赖（本地翻译档读字用）"
OS="$(uname -s)"; ARCH="$(uname -m)"; NEED_PIN=0
if [ "$OS" = "Darwin" ]; then
  MACV="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"
  if [ "$ARCH" = "x86_64" ] && [ "${MACV:-0}" -lt 13 ]; then NEED_PIN=1; fi
fi
if [ "$NEED_PIN" = "1" ]; then
  warn "macOS ${MACV} + ${ARCH}：钉 opencv 4.9.0.80 + numpy 1.26.4（避免源码编译）"
  pip_install "opencv-python-headless==4.9.0.80" "numpy==1.26.4" pyclipper shapely PyYAML six tqdm \
    || die "OCR 依赖安装失败"
else
  pip_install opencv-python-headless pyclipper shapely PyYAML six tqdm || die "OCR 依赖安装失败"
fi
pip_install --no-deps rapidocr-onnxruntime || die "rapidocr 安装失败"

# ---------------------------------------------------------------- 4. 抠图模型
say "4/5 抠图模型（一次性下载，之后全离线）"
mkdir -p "$MODELS"
fetch_model() {  # fetch_model <名字>
  local name="$1" dest="$MODELS/$1.onnx"
  [ -s "$dest" ] && { ok "$name.onnx 已存在（$(du -h "$dest" | cut -f1)）"; return 0; }
  for m in "${MIRRORS[@]}"; do
    local url="${m}https://github.com/danielgatis/rembg/releases/download/v0.0.0/$name.onnx"
    printf '   下载 %s … ' "$name.onnx"
    if curl -fL --max-time 900 --connect-timeout 20 -o "$dest.part" "$url" 2>/dev/null; then
      mv "$dest.part" "$dest"; ok "$(du -h "$dest" | cut -f1)  来自 ${m:-直连}"
      return 0
    fi
    printf '失败，换通道\n'; rm -f "$dest.part"
  done
  warn "$name.onnx 下载失败 —— 手动下载后放到 $dest"
  return 1
}
fetch_model u2net || true
[ "$WITH_ISNET" = "1" ] && { fetch_model isnet-general-use || true; }

# ---------------------------------------------------------------- 5. 自检
say "5/5 自检"
MODELS_DIR="$MODELS" "$PYBIN" - <<'PY'
import importlib.metadata as md, os, sys, pathlib
bad = []
for p in ("pillow", "numpy", "onnxruntime", "rapidocr-onnxruntime", "opencv-python-headless"):
    try: print(f"   ✓ {p:24s} {md.version(p)}")
    except Exception: bad.append(p); print(f"   ✗ {p:24s} 缺失")
try:
    import cv2, onnxruntime, rapidocr_onnxruntime  # noqa
except Exception as e:
    bad.append(f"import: {e}"); print(f"   ✗ 导入失败：{e}")
mdir = pathlib.Path(os.environ.get("MODELS_DIR") or (pathlib.Path.home() / ".hermes" / "venvs" / "models"))
for m in ("u2net", "isnet-general-use"):
    p = mdir / f"{m}.onnx"
    print(f"   {'✓' if p.exists() else '·'} 模型 {m:20s} {'已就位' if p.exists() else '未下载（可选）'}")
sys.exit(1 if bad else 0)
PY
[ $? -eq 0 ] || die "自检不通过，把上面输出贴回"

say "完成"
cat <<'NEXT'
下一步（不需要任何凭证）：
  1) 白底图：  python3 ~/.hermes/skills/ecom-product-images/scripts/imgctl.py white --image 图.jpg --engine local
  2) 整套图：  python3 .../imgctl.py set --images 图.jpg --platform takealot --gallery 5 --detail 5 --composite
  3) 图片翻译：python3 .../imgctl.py translate --image 图.jpg --to en --mode local
  4) 通道自检：python3 .../imgctl.py doctor
需要云端保真翻译/抠图时，另配阿里云 AccessKey（见 references/providers.md），不需重装。
NEXT
