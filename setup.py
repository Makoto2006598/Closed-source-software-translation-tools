"""
setup.py — py2app 打包配置

用法：
  python setup.py py2app          # 构建 .app bundle（输出到 dist/）
  python setup.py py2app --alias  # 开发模式（不复制文件，调试用）
"""

from setuptools import setup

APP = ["main.py"]

DATA_FILES = [
    # 将翻译表和配置模板打包进 .app（用户可在 .app 同级目录覆盖）
    ("", ["translations.json", "config.json"]),
]

OPTIONS = {
    # 不模拟 sys.argv[0]（py2app 开启此项有时导致崩溃）
    "argv_emulation": False,

    # 需要完整打包的包（仅列出 py2app 自动分析会遗漏的）
    # 注意：不要列出不确定是否安装的包！
    # py2app 的 collect_packagedirs 会对每个包调用 imp.find_module()，
    # 任何一个找不到都会导致 ImportError 构建失败。
    # 其余包由 py2app 的 modulegraph 和 recipe 系统自动发现。
    "packages": [
        "anthropic",       # 有大量动态导入的子模块，必须完整打包
    ],

    # 需要显式包含的模块（py2app 自动分析可能遗漏的）
    "includes": [
        # 项目内部模块
        "overlay",
        "translator",
        "translation_extractor",
        # anthropic 的关键传递依赖（以 includes 而非 packages 方式引入，更安全）
        "httpx",
        "httpcore",
        "anyio",
        "sniffio",
        "h11",
        "certifi",
        "idna",
        "dotenv",
        # 标准库中 py2app 可能遗漏的模块
        "json",
        "logging",
        "threading",
        "plistlib",
        "shutil",
    ],

    # 明确排除不需要的包，减小体积
    "excludes": [
        "tkinter",
        "wx",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "matplotlib",
        "numpy",
        "scipy",
        "PIL",
    ],

    # Info.plist 配置
    "plist": {
        # 应用基本信息
        "CFBundleName": "Claude UI Localizer",
        "CFBundleDisplayName": "Claude UI Localizer",
        "CFBundleIdentifier": "com.claude-ui-localizer",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        # CFBundleExecutable 由 py2app 自动设置，手动指定会导致 .app 无法启动

        # 权限说明（macOS 系统要求明确声明用途）
        "NSAppleEventsUsageDescription": (
            "Claude UI Localizer 需要读取其他应用的 UI 元素位置，"
            "以便在正确的位置叠加显示中文翻译。"
        ),

        # 后台工具模式：不显示 Dock 图标，不出现在 App Switcher
        "LSUIElement": True,

        # 支持 Retina 高分辨率显示
        "NSHighResolutionCapable": True,

        # 声明支持的最低 macOS 版本
        "LSMinimumSystemVersion": "12.0",

        # 版权信息
        "NSHumanReadableCopyright": "MIT License",
    },

    # 完整打包（包含所有依赖，用户无需安装 Python）
    "semi_standalone": False,
    "site_packages": True,

    # 如果有应用图标，取消注释并提供 .icns 文件
    # "iconfile": "icon.icns",
}

setup(
    app=APP,
    name="Claude UI Localizer",
    version="1.0.0",
    description="非侵入式 macOS 应用 UI 汉化工具",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    # py2app 通过 pip 安装，不使用已废弃的 setup_requires
)
