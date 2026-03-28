"""
main.py — Claude UI Localizer 主入口

启动流程：
1. 加载 config.json
2. 检查翻译表是否存在，不存在则自动提取并翻译
3. 检查 Accessibility 权限
4. 等待 Claude.app 启动
5. 启动 Overlay 监控服务
"""

import json
import logging
import os
import sys
import time
import threading

def _get_app_support_dir() -> str:
    """获取用户可写的数据目录：~/Library/Application Support/ClaudeUILocalizer/"""
    app_support = os.path.join(
        os.path.expanduser("~"), "Library", "Application Support", "ClaudeUILocalizer"
    )
    os.makedirs(app_support, exist_ok=True)
    return app_support


# 日志写到用户目录（.app bundle 内部只读）
_log_path = os.path.join(_get_app_support_dir(), "localizer.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_path, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# 资源目录（bundle 内随附的 config/translations 模板）
_BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
# 可写数据目录（翻译更新写到这里，优先读取）
_DATA_DIR = _get_app_support_dir()

CONFIG_PATH = os.path.join(_BUNDLE_DIR, "config.json")
TRANSLATIONS_PATH = os.path.join(_DATA_DIR, "translations.json")

# 首次运行时：将 bundle 内置翻译表复制到用户目录（之后可安全写入）
_bundled_translations = os.path.join(_BUNDLE_DIR, "translations.json")
if not os.path.exists(TRANSLATIONS_PATH) and os.path.exists(_bundled_translations):
    import shutil
    shutil.copy2(_bundled_translations, TRANSLATIONS_PATH)
    logging.getLogger(__name__).info(f"已复制内置翻译表到 {TRANSLATIONS_PATH}")


def load_config() -> dict:
    """加载配置文件，缺少字段时使用默认值。"""
    defaults = {
        "claude_app_path": "/Applications/Claude.app",
        "api_key": "",
        "target_language": "zh-CN",
        "refresh_interval": 1.5,
        "overlay_opacity": 0.95,
        "font_name": "PingFangSC-Regular",
        "font_size_offset": -1,
    }
    if not os.path.exists(CONFIG_PATH):
        logger.warning(f"config.json 不存在，使用默认配置（{CONFIG_PATH}）")
        return defaults

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        return {**defaults, **user_config}
    except json.JSONDecodeError as e:
        logger.error(f"config.json 格式错误：{e}，使用默认配置")
        return defaults


def ensure_translations(config: dict):
    """
    确保翻译文件存在且包含已翻译的条目。
    如果文件不存在：先提取字符串，再调用 Claude API 翻译。
    如果文件存在但有未翻译条目（值为空）：只翻译空条目。
    """
    needs_extraction = not os.path.exists(TRANSLATIONS_PATH)
    needs_translation = False

    if needs_extraction:
        logger.info("翻译文件不存在，开始提取 Claude.app UI 字符串...")
        try:
            from translation_extractor import extract_and_save
            extract_and_save(
                app_path=config.get("claude_app_path", "/Applications/Claude.app"),
                output_path=TRANSLATIONS_PATH,
            )
        except Exception as e:
            logger.error(f"字符串提取失败：{e}")
            logger.info("将使用内置翻译表继续运行")
            return

    # 检查是否有未翻译条目
    try:
        with open(TRANSLATIONS_PATH, "r", encoding="utf-8") as f:
            translations = json.load(f)
        pending = [k for k, v in translations.items() if not v]
        needs_translation = len(pending) > 0
    except Exception:
        needs_translation = False

    if needs_translation:
        api_key = config.get("api_key", "").strip()
        if not api_key:
            logger.warning(
                "API Key 未配置，跳过自动翻译。\n"
                "请在 config.json 中填入 api_key，或手工编辑 translations.json"
            )
            return

        logger.info(f"发现 {len(pending)} 条未翻译的字符串，开始自动翻译...")
        try:
            from translator import translate_all_pending
            translate_all_pending(TRANSLATIONS_PATH, api_key)
            logger.info("自动翻译完成")
        except Exception as e:
            logger.error(f"自动翻译失败：{e}")


def wait_for_claude_app(bundle_id: str = "com.anthropic.claude", timeout: float = 0) -> bool:
    """
    等待 Claude.app 启动。timeout=0 表示无限等待。
    返回 True 表示检测到 Claude.app 正在运行。
    """
    try:
        from AppKit import NSRunningApplication
        PYOBJC_AVAILABLE = True
    except ImportError:
        PYOBJC_AVAILABLE = False

    if not PYOBJC_AVAILABLE:
        logger.warning("PyObjC 不可用，无法检测 Claude.app 状态")
        return False

    logger.info("等待 Claude.app 启动...")
    start = time.time()
    while True:
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps and len(apps) > 0:
            logger.info("检测到 Claude.app 正在运行")
            return True
        if timeout > 0 and (time.time() - start) > timeout:
            logger.warning("等待 Claude.app 超时")
            return False
        time.sleep(2.0)


def run_overlay(config: dict):
    """在主线程启动 Overlay 服务（NSApplication RunLoop）。"""
    try:
        from AppKit import NSApplication
        from overlay import ClaudeOverlay, check_accessibility_permission
    except ImportError as e:
        logger.error(f"无法导入 Overlay 模块：{e}")
        logger.error("请确认已安装 PyObjC：pip install -r requirements.txt")
        sys.exit(1)

    if not check_accessibility_permission():
        logger.error(
            "\n[权限不足] 需要 Accessibility（辅助功能）权限\n"
            "请按以下步骤操作：\n"
            "  1. 打开「系统设置」→「隐私与安全性」→「辅助功能」\n"
            "  2. 点击「+」，添加「终端」或「Python」\n"
            "  3. 确保开关已打开，然后重新运行本程序\n"
        )
        sys.exit(1)

    overlay = ClaudeOverlay(TRANSLATIONS_PATH, config)

    # 在后台线程运行监控循环，主线程运行 NSRunLoop（macOS UI 必须在主线程）
    monitor_thread = threading.Thread(
        target=overlay.start_monitoring,
        name="OverlayMonitor",
        daemon=True,
    )
    monitor_thread.start()

    try:
        app = NSApplication.sharedApplication()
        app.run()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
        overlay.stop()


def main():
    logger.info("=== Claude UI Localizer 启动 ===")

    # 检查运行平台
    if sys.platform != "darwin":
        logger.error("本工具仅支持 macOS，当前系统：" + sys.platform)
        sys.exit(1)

    # 1. 加载配置
    config = load_config()
    logger.info(f"配置加载完成，刷新间隔：{config['refresh_interval']}s")

    # 2. 确保翻译文件存在且已翻译
    ensure_translations(config)

    # 3. 等待 Claude.app 启动
    wait_for_claude_app()

    # 4. 启动 Overlay
    run_overlay(config)


if __name__ == "__main__":
    main()
