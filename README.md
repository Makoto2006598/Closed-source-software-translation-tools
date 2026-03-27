# Claude UI Localizer

非侵入式 macOS 应用 UI 汉化工具，通过透明 Overlay 将 Claude.app 的英文界面实时显示为简体中文。

## 工作原理

本工具采用**方案 C：启动脚本 + Overlay 系统**：

1. 扫描 Claude.app 内的 UI 字符串（`.strings`、`.plist` 文件）
2. 调用 Claude API 自动批量翻译
3. 在 Claude.app 窗口之上创建一层透明浮窗（Overlay）
4. 通过 macOS Accessibility API 实时获取 UI 元素位置
5. 在对应位置叠加显示简体中文翻译

鼠标点击可穿透 Overlay 直接操作 Claude.app，视觉上实现汉化效果。

## 系统要求

- macOS 12 (Monterey) 或更高版本
- Python 3.10+
- Claude.app 已安装
- Anthropic API Key（用于自动翻译）

## 快速开始

### 1. 安装

```bash
git clone https://github.com/makoto2006598/closed-source-software-translation-tools.git
cd closed-source-software-translation-tools
bash setup.sh
```

### 2. 配置

编辑 `config.json`，填入您的 Anthropic API Key：

```json
{
  "claude_app_path": "/Applications/Claude.app",
  "api_key": "sk-ant-xxxxxxxxxxxxxxxx",
  "target_language": "zh-CN",
  "refresh_interval": 1.5
}
```

### 3. 运行

```bash
python3 main.py
```

首次运行会自动提取 Claude.app 的 UI 字符串并翻译。之后打开 Claude.app，即可看到中文界面。

## 项目结构

```
├── main.py                    # 主入口
├── overlay.py                 # Overlay 显示服务（PyObjC）
├── translation_extractor.py   # 提取 Claude.app UI 字符串
├── translator.py              # 调用 Claude API 批量翻译
├── translations.json          # 翻译映射表（可手工编辑）
├── config.json                # 配置文件
├── requirements.txt           # Python 依赖
└── setup.sh                   # 安装脚本
```

## 权限说明

本工具需要 macOS **辅助功能（Accessibility）** 权限，用于读取其他应用的 UI 元素信息。

设置路径：「系统设置」→「隐私与安全性」→「辅助功能」→ 添加终端或 Python

## 自定义翻译

`translations.json` 是纯 JSON 文件，格式为 `{"英文原文": "中文翻译"}`，可直接手工编辑修改翻译内容。

## 注意事项

- Claude.app 更新后可能需要重新运行字符串提取
- 翻译 Overlay 为纯视觉叠加，不修改 Claude.app 任何文件
- 仅支持 macOS，不支持 Windows / Linux

## 许可证

MIT License
