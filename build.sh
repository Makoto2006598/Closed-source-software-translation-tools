#!/bin/bash
# build.sh — Claude UI Localizer macOS DMG 构建脚本
#
# 用法：
#   bash build.sh              # 构建 DMG
#   bash build.sh --version X  # 指定版本号（默认 1.0.0）
#   bash build.sh --clean      # 仅清理构建目录

set -e

APP_NAME="Claude UI Localizer"
VERSION="1.0.0"
BUNDLE_ID="com.claude-ui-localizer"

# ── 参数解析 ──────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            VERSION="$2"; shift 2 ;;
        --clean)
            echo "清理构建目录..."
            rm -rf build/ dist/ *.egg-info/
            echo "[✓] 清理完成"
            exit 0 ;;
        *)
            echo "未知参数：$1"; exit 1 ;;
    esac
done

DMG_NAME="${APP_NAME// /-}-v${VERSION}.dmg"   # Claude-UI-Localizer-v1.0.0.dmg
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/${DMG_NAME}"

# ── 环境检查 ──────────────────────────────────────
echo "=== Claude UI Localizer 构建脚本 ==="
echo "版本：$VERSION"
echo ""

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "[错误] 必须在 macOS 上构建，当前系统：$(uname -s)"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "[错误] 未找到 Python 3"
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "[✓] Python $PY_VERSION"

# ── 安装依赖 ──────────────────────────────────────
echo ""
echo "=== 安装构建依赖 ==="
$PYTHON -m pip install --quiet -r requirements.txt
$PYTHON -m pip install --quiet "py2app>=0.28.6"
echo "[✓] 依赖安装完成"

# ── 清理旧构建 ────────────────────────────────────
echo ""
echo "=== 清理旧构建 ==="
rm -rf build/ dist/ Claude_UI_Localizer.egg-info/ "Claude UI Localizer.egg-info/"
echo "[✓] 清理完成"

# ── 构建 .app bundle ──────────────────────────────
echo ""
echo "=== 构建 .app bundle ==="
$PYTHON setup.py py2app 2>&1

if [ ! -d "$APP_PATH" ]; then
    echo "[错误] .app 构建失败，未找到：$APP_PATH"
    exit 1
fi
echo "[✓] .app bundle 已生成：$APP_PATH"

# ── 更新版本号到 Info.plist ───────────────────────
INFO_PLIST="${APP_PATH}/Contents/Info.plist"
if [ -f "$INFO_PLIST" ]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$INFO_PLIST" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$INFO_PLIST" 2>/dev/null || true
    echo "[✓] 版本号已更新至 $VERSION"
fi

# ── 可选：代码签名（需要 Apple 开发者账号）────────
# 如果设置了 CODESIGN_IDENTITY 环境变量，则进行签名
if [ -n "$CODESIGN_IDENTITY" ]; then
    echo ""
    echo "=== 代码签名 ==="
    codesign --force --deep --sign "$CODESIGN_IDENTITY" \
        --entitlements entitlements.plist \
        "$APP_PATH"
    echo "[✓] 代码签名完成（$CODESIGN_IDENTITY）"
else
    echo ""
    echo "[提示] 未设置 CODESIGN_IDENTITY，跳过代码签名"
    echo "       用户首次打开时需右键→「打开」以绕过 Gatekeeper"
fi

# ── 创建 DMG ──────────────────────────────────────
echo ""
echo "=== 创建 DMG ==="
mkdir -p dist

TMP_DIR=$(mktemp -d)
echo "临时目录：$TMP_DIR"

# 复制 .app 到临时目录
cp -r "$APP_PATH" "$TMP_DIR/"

# 创建 Applications 快捷方式（用户拖拽安装体验）
ln -s /Applications "$TMP_DIR/Applications"

# 用 hdiutil 创建压缩 DMG（UDZO = zlib 压缩格式）
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$TMP_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

rm -rf "$TMP_DIR"

if [ ! -f "$DMG_PATH" ]; then
    echo "[错误] DMG 创建失败"
    exit 1
fi

DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
echo "[✓] DMG 已生成：$DMG_PATH（$DMG_SIZE）"

# ── 完成 ──────────────────────────────────────────
echo ""
echo "=== 构建完成 ==="
echo "  .app : $APP_PATH"
echo "  .dmg : $DMG_PATH"
echo ""
echo "用户安装方式："
echo "  1. 双击 $DMG_NAME 挂载"
echo "  2. 将「${APP_NAME}」拖入 Applications 文件夹"
echo "  3. 右键→打开（首次运行需绕过 Gatekeeper）"
