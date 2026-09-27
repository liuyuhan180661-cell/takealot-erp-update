# 可选技能包（Hermes skills）

这个目录里的技能是**独立可装的 Hermes skill**，和 ERP 更新包无关——客户机可以单独拉取安装，不需要走 ERP 自更新。
（本目录不影响 `update.json` / 更新包的校验流程。）

## 安装到客户机（二选一）

**A. 有 git（推荐）**
```bash
git clone --depth 1 https://github.com/liuyuhan180661-cell/takealot-erp-update.git /tmp/skills-src
mkdir -p ~/.hermes/skills
cp -R /tmp/skills-src/skills/ecom-product-images ~/.hermes/skills/
```
Windows（PowerShell）：
```powershell
git clone --depth 1 https://github.com/liuyuhan180661-cell/takealot-erp-update.git $env:TEMP\skills-src
New-Item -ItemType Directory -Force "$env:USERPROFILE\.hermes\skills" | Out-Null
Copy-Item -Recurse -Force "$env:TEMP\skills-src\skills\ecom-product-images" "$env:USERPROFILE\.hermes\skills\"
```

**B. 没有 git**：直接从 GitHub 页面下载目录（或用 `curl` 拉单个文件），放进 `~/.hermes/skills/ecom-product-images/`。

## 装完做两件事

```bash
# 1) 装依赖（只有地址，无二进制；约 1 分钟，含 168MB 抠图模型）
bash ~/.hermes/skills/ecom-product-images/scripts/install.sh          # Windows: scripts\install.ps1
# 2) 自证
python3 ~/.hermes/skills/ecom-product-images/scripts/imgctl.py doctor
```

`doctor` 里出现 OK 就可以用了；云端翻译档（阿里云/百炼）配好 key 会自动生效，不需要重装。

## 目录里的技能

| 技能 | 干什么 | 外部依赖 |
|---|---|---|
| `ecom-product-images` | 一张产品图 → 白底图／整套套图／场景图／图片翻译（云端+本地三档路由） | 无（install 脚本自带；云端档可选配 key） |
