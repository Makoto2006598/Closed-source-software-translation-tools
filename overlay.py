"""
overlay.py — Claude UI Localizer 的 Overlay 显示服务

通过 PyObjC 和 macOS Accessibility API 在 Claude.app 窗口之上
创建透明浮窗，叠加显示中文翻译。
"""

import json
import time
import threading
import logging
from typing import Optional

try:
    from AppKit import (
        NSApplication,
        NSWindow,
        NSTextField,
        NSColor,
        NSFont,
        NSView,
        NSBorderlessWindowMask,
        NSFloatingWindowLevel,
        NSMakeRect,
        NSRunningApplication,
        NSWorkspace,
        NSAppearance,
    )
    from ApplicationServices import (
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        AXUIElementCopyAttributeNames,
        kAXValueAttribute,
        kAXFrameAttribute,
        kAXChildrenAttribute,
        kAXRoleAttribute,
        kAXTitleAttribute,
        kAXWindowsAttribute,
        kAXFocusedWindowAttribute,
    )
    from Foundation import NSMakeRect, NSRect, NSPoint, NSSize
    import objc
    PYOBJC_AVAILABLE = True
except ImportError:
    PYOBJC_AVAILABLE = False
    logging.warning("PyObjC 未安装，Overlay 功能不可用。请运行：pip install pyobjc")

logger = logging.getLogger(__name__)


def check_accessibility_permission() -> bool:
    """检查是否拥有 Accessibility 权限，未授权时弹出系统引导对话框。"""
    if not PYOBJC_AVAILABLE:
        return False
    trusted = AXIsProcessTrusted()
    if not trusted:
        logger.warning("缺少 Accessibility 权限，正在请求授权...")
        options = {"AXTrustedCheckOptionPrompt": True}
        AXIsProcessTrustedWithOptions(options)
    return bool(trusted)


def get_running_app_pid(bundle_id: str) -> Optional[int]:
    """通过 bundle ID 获取正在运行的应用的 PID。"""
    if not PYOBJC_AVAILABLE:
        return None
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
    if apps and len(apps) > 0:
        return apps[0].processIdentifier()
    return None


def ax_get_attribute(element, attribute: str):
    """从 AX 元素中安全地获取属性值，失败时返回 None。"""
    try:
        error, value = AXUIElementCopyAttributeValue(element, attribute, None)
        if error == 0:
            return value
    except Exception:
        pass
    return None


def collect_text_elements(element, results: list, depth: int = 0, max_depth: int = 20):
    """
    递归遍历 AX 树，收集所有包含文本的 UI 元素。

    results 中每个条目格式：
    {"text": str, "frame": (x, y, w, h)}
    """
    if depth > max_depth:
        return

    role = ax_get_attribute(element, kAXRoleAttribute)
    value = ax_get_attribute(element, kAXValueAttribute)
    title = ax_get_attribute(element, kAXTitleAttribute)
    frame = ax_get_attribute(element, kAXFrameAttribute)

    text = None
    if isinstance(value, str) and value.strip():
        text = value.strip()
    elif isinstance(title, str) and title.strip():
        text = title.strip()

    if text and frame:
        try:
            origin = frame.origin
            size = frame.size
            results.append({
                "text": text,
                "frame": (origin.x, origin.y, size.width, size.height),
                "role": str(role) if role else "",
            })
        except Exception:
            pass

    children = ax_get_attribute(element, kAXChildrenAttribute)
    if children:
        for child in children:
            collect_text_elements(child, results, depth + 1, max_depth)


class OverlayLabel:
    """代表 Overlay 上的一个翻译标签（中文文本）。"""

    def __init__(self, parent_view: "NSView", text: str, frame: tuple, config: dict):
        x, y, w, h = frame
        font_name = config.get("font_name", "PingFangSC-Regular")
        font_size = max(10.0, h * 0.65 + config.get("font_size_offset", -1))

        self.label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(x, y, w + 20, h)
        )
        self.label.setStringValue_(text)
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(True)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setFont_(NSFont.fontWithName_size_(font_name, font_size)
                            or NSFont.systemFontOfSize_(font_size))

        # 根据当前外观设置背景色和文字颜色
        self._apply_appearance(config)

        parent_view.addSubview_(self.label)

    def _apply_appearance(self, config: dict):
        """根据深色/浅色模式设置颜色。"""
        if not PYOBJC_AVAILABLE:
            return
        try:
            appearance_name = str(NSAppearance.currentAppearance().name())
            is_dark = "Dark" in appearance_name
        except Exception:
            is_dark = False

        if is_dark:
            self.label.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(
                0.15, 0.15, 0.18, config.get("overlay_opacity", 0.95)
            ))
            self.label.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(
                0.9, 0.9, 0.9, 1.0
            ))
        else:
            self.label.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(
                0.98, 0.98, 0.98, config.get("overlay_opacity", 0.95)
            ))
            self.label.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(
                0.1, 0.1, 0.1, 1.0
            ))

    def remove(self):
        self.label.removeFromSuperview()


class ClaudeOverlay:
    """
    主 Overlay 控制器。

    在 Claude.app 窗口之上创建透明浮窗，并通过 Accessibility API
    实时获取 UI 元素位置，叠加显示中文翻译。
    """

    CLAUDE_BUNDLE_ID = "com.anthropic.claude"

    def __init__(self, translations_file: str, config: dict):
        self.config = config
        self.translations: dict[str, str] = {}
        self.overlay_window: Optional[object] = None
        self.overlay_view: Optional[object] = None
        self.active_labels: list[OverlayLabel] = []
        self._prev_element_snapshot: list = []
        self._running = False
        self._lock = threading.Lock()

        self._load_translations(translations_file)

    def _load_translations(self, path: str):
        """加载翻译映射表。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
            logger.info(f"已加载 {len(self.translations)} 条翻译")
        except FileNotFoundError:
            logger.error(f"翻译文件不存在：{path}")
        except json.JSONDecodeError as e:
            logger.error(f"翻译文件格式错误：{e}")

    def _get_claude_window_frame(self, pid: int) -> Optional[tuple]:
        """获取 Claude.app 主窗口的坐标和尺寸。"""
        app_element = AXUIElementCreateApplication(pid)
        windows = ax_get_attribute(app_element, kAXWindowsAttribute)
        if not windows:
            return None
        window = windows[0]
        frame = ax_get_attribute(window, kAXFrameAttribute)
        if frame:
            return (
                frame.origin.x,
                frame.origin.y,
                frame.size.width,
                frame.size.height,
            )
        return None

    def _create_overlay_window(self, frame: tuple):
        """创建覆盖在 Claude.app 之上的透明浮窗。"""
        if not PYOBJC_AVAILABLE:
            return

        x, y, w, h = frame

        self.overlay_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h),
            NSBorderlessWindowMask,
            2,  # NSBackingStoreBuffered
            False,
        )
        self.overlay_window.setBackgroundColor_(NSColor.clearColor())
        self.overlay_window.setAlphaValue_(1.0)
        self.overlay_window.setIgnoresMouseEvents_(True)
        self.overlay_window.setLevel_(NSFloatingWindowLevel)
        self.overlay_window.setOpaque_(False)
        self.overlay_window.setHasShadow_(False)

        self.overlay_view = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, w, h)
        )
        self.overlay_window.setContentView_(self.overlay_view)
        self.overlay_window.makeKeyAndOrderFront_(None)

        logger.info(f"Overlay 窗口已创建，尺寸：{w}x{h}")

    def _update_overlay_position(self, frame: tuple):
        """同步 Overlay 窗口位置和大小到 Claude.app 窗口。"""
        if not self.overlay_window:
            return
        x, y, w, h = frame
        self.overlay_window.setFrame_display_(
            NSMakeRect(x, y, w, h), True
        )
        self.overlay_view.setFrame_(NSMakeRect(0, 0, w, h))

    def _clear_labels(self):
        """移除所有当前显示的翻译标签。"""
        for label in self.active_labels:
            label.remove()
        self.active_labels.clear()

    def _render_translations(self, elements: list):
        """根据 UI 元素列表，在 Overlay 上渲染翻译文本。"""
        self._clear_labels()
        for elem in elements:
            text = elem.get("text", "")
            frame = elem.get("frame")
            if not text or not frame:
                continue
            translated = self.translations.get(text)
            if translated and self.overlay_view:
                label = OverlayLabel(self.overlay_view, translated, frame, self.config)
                self.active_labels.append(label)

    def _elements_changed(self, new_elements: list) -> bool:
        """检查 UI 元素是否发生变化（差分比较，避免不必要的重绘）。"""
        if len(new_elements) != len(self._prev_element_snapshot):
            return True
        for a, b in zip(new_elements, self._prev_element_snapshot):
            if a.get("text") != b.get("text") or a.get("frame") != b.get("frame"):
                return True
        return False

    def update_overlay(self):
        """一次完整的 Overlay 更新周期。"""
        if not PYOBJC_AVAILABLE:
            return

        pid = get_running_app_pid(self.CLAUDE_BUNDLE_ID)
        if not pid:
            # Claude.app 未运行，隐藏 Overlay
            if self.overlay_window:
                self.overlay_window.orderOut_(None)
            return

        window_frame = self._get_claude_window_frame(pid)
        if not window_frame:
            return

        # 创建或更新 Overlay 窗口位置
        if not self.overlay_window:
            self._create_overlay_window(window_frame)
        else:
            self._update_overlay_position(window_frame)
            self.overlay_window.orderFront_(None)

        # 收集 Claude.app 的 UI 元素
        app_element = AXUIElementCreateApplication(pid)
        elements: list = []
        collect_text_elements(app_element, elements)

        # 差分更新：只在内容变化时重绘
        with self._lock:
            if self._elements_changed(elements):
                self._render_translations(elements)
                self._prev_element_snapshot = elements

    def start_monitoring(self):
        """启动后台监控循环，定期更新 Overlay。"""
        if not PYOBJC_AVAILABLE:
            logger.error("PyObjC 不可用，无法启动 Overlay")
            return

        if not check_accessibility_permission():
            logger.error(
                "尚未获得 Accessibility 权限。\n"
                "请在「系统设置 → 隐私与安全性 → 辅助功能」中授权后重新运行。"
            )
            return

        self._running = True
        interval = self.config.get("refresh_interval", 1.5)
        logger.info(f"Overlay 监控已启动，刷新间隔：{interval}s")

        while self._running:
            try:
                self.update_overlay()
            except Exception as e:
                logger.error(f"Overlay 更新出错：{e}")
            time.sleep(interval)

    def stop(self):
        """停止监控并关闭 Overlay 窗口。"""
        self._running = False
        if self.overlay_window:
            self.overlay_window.orderOut_(None)
        logger.info("Overlay 已停止")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    config = json.load(open("config.json"))
    overlay = ClaudeOverlay("translations.json", config)

    if PYOBJC_AVAILABLE:
        app = NSApplication.sharedApplication()
        # 在后台线程启动监控，主线程运行 NSRunLoop（UI 必须在主线程）
        monitor_thread = threading.Thread(target=overlay.start_monitoring, daemon=True)
        monitor_thread.start()
        app.run()
    else:
        print("PyObjC 不可用，请先安装依赖：pip install -r requirements.txt")
