#!/bin/bash
# Claude UI Localizer — 安装脚本

set -e

echo "=== Claude UI Localizer 安装程序 ==="
echo ""

# 1. 检查 Python 版本
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "[错误] 未找到 Python，请先安装 Python 3.10 或更高版本"
    exit 1
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "[错误] 需要 Python 3.10 或更高版本，当前版本：$PY_VERSION"
    exit 1
fi
echo "[✓] Python $PY_VERSION"

# 2. 安装依赖
echo ""
echo "正在安装 Python 依赖..."
$PYTHON -m pip install -r requirements.txt
echo "[✓] 依赖安装完成"

# 3. 检查 Claude.app 是否存在
if [ ! -d "/Applications/Claude.app" ]; then
    echo ""
    echo "[警告] 未找到 /Applications/Claude.app，请确认 Claude 桌面应用已安装"
fi

# 4. 提示配置 API Key
echo ""
echo "=== 配置 API Key ==="
if [ -f "config.json" ]; then
    CURRENT_KEY=$(python3 -c "import json; d=json.load(open('config.json')); print(d.get('api_key',''))" 2>/dev/null || echo "")
    if [ -z "$CURRENT_KEY" ]; then
        echo "请在 config.json 中填入您的 Anthropic API Key："
        echo "  \"api_key\": \"sk-ant-...\""
    else
        echo "[✓] API Key 已配置"
    fi
fi

# 5. 提示开启辅助功能权限
echo ""
echo "=== 开启辅助功能权限 ==="
echo "运行本工具需要 macOS 辅助功能（Accessibility）权限"
echo "请按以下步骤操作："
echo "  1. 打开「系统设置」→「隐私与安全性」→「辅助功能」"
echo "  2. 点击「+」按钮，添加「终端」或「Python」应用"
echo "  3. 确保开关已打开"
echo ""

# 6. 可选：创建 launchd plist 实现开机自启
read -r -p "是否设置开机自启动？(y/N) " AUTOSTART
if [[ "$AUTOSTART" =~ ^[Yy]$ ]]; then
    SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
    PLIST_PATH="$HOME/Library/LaunchAgents/com.claude-ui-localizer.plist"
    cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-ui-localizer</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/main.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/localizer.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/localizer.log</string>
</dict>
</plist>
EOF
    launchctl load "$PLIST_PATH" 2>/dev/null || true
    echo "[✓] 已设置开机自启：$PLIST_PATH"
fi

echo ""
echo "=== 安装完成 ==="
echo "运行方式：python3 main.py"
echo ""
