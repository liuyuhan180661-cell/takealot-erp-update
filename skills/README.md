# 可选技能包（Hermes skills）

这个目录里的技能是**独立可装的 Hermes skill**，和 ERP 更新包无关——客户机可以单独拉取安装，不需要走 ERP 自更新。
（本目录不影响 `update.json` / 更新包的校验流程。）

## 安装到客户机（二选一）

**A. 有 git（推荐）** —— 把 `<技能名>` 换成下面表格里你要的那个：

```bash
git clone --depth 1 https://github.com/liuyuhan180661-cell/takealot-erp-update.git /tmp/skills-src
mkdir -p ~/.hermes/skills
cp -R /tmp/skills-src/skills/<技能名> ~/.hermes/skills/
```
Windows（PowerShell）：
```powershell
git clone --depth 1 https://github.com/liuyuhan180661-cell/takealot-erp-update.git $env:TEMP\skills-src
New-Item -ItemType Directory -Force "$env:USERPROFILE\.hermes\skills" | Out-Null
Copy-Item -Recurse -Force "$env:TEMP\skills-src\skills\<技能名>" "$env:USERPROFILE\.hermes\skills\"
```

**B. 没有 git**：直接从 GitHub 页面下载目录（或用 `curl` 拉单个文件），放进 `~/.hermes/skills/<技能名>/`。

## 目录里的技能

| 技能 | 干什么 | 外部依赖 |
|---|---|---|
| `ecom-product-images` | 一张产品图 → 白底图／整套套图／场景图／图片翻译（云端+本地三档路由） | 无（install 脚本自带；云端档可选配 key） |
| `takealot-portal-cua` | 在 Takealot 卖家后台建/改 listing（新建、拆解重塑、上传图片、类目向导）+ 断言式验收 | ① 首选：一个 Chrome/Edge + `websocket-client`；② 兜底：官方 BrowserSkill（`bsk` CLI + 扩展） |

## 装完做两件事

**`ecom-product-images`**
```bash
# 1) 装依赖（只有地址，无二进制；约 1 分钟，含 168MB 抠图模型）
bash ~/.hermes/skills/ecom-product-images/scripts/install.sh          # Windows: scripts\install.ps1
# 2) 自证
python3 ~/.hermes/skills/ecom-product-images/scripts/imgctl.py doctor
```
`doctor` 里出现 OK 就可以用了；云端翻译档（阿里云/百炼）配好 key 会自动生效，不需要重装。

**`takealot-portal-cua`**（需要先在卖家后台登录一次，见技能内 SKILL.md「交付前置」）
```bash
cd ~/.hermes/skills/takealot-portal-cua/scripts
# 1) CDP 路依赖（一次即可；慢就走镜像 -i https://pypi.tuna.tsinghua.edu.cn/simple）
python3 -m pip install websocket-client
# 2) 自证：CDP 通不通 / bsk 兜底通不通 / 浏览器在哪
python3 run_listing.py --check
# 3) 起一个带调试端口的独立浏览器（首次在弹出的窗口里登录一次，登录态长期复用）
python3 cdp_browser.py --start
```
之后建 listing 一条命令：`python3 run_listing.py facts_X.json`（默认走 CDP，连不上自动退 `bsk`）。
没有 Chrome/Edge 或不想装 `websocket-client` 时：`python3 run_listing.py --driver bsk`，按技能内 `references/bsk-setup.md` 装官方扩展即可。
