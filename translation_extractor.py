"""
translation_extractor.py — 从 Claude.app 提取 UI 字符串

扫描 Claude.app/Contents/Resources/ 目录下的：
- *.strings  (Cocoa 本地化文件)
- *.plist    (配置文件)
- en.lproj/  (英文原文优先)

将提取到的英文字符串写入 translations.json（值为空字符串，待翻译）。
不覆盖已有的翻译结果。
"""

import json
import logging
import os
import plistlib
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# .strings 文件解析（Apple 专有格式）
# ──────────────────────────────────────────────

def parse_strings_file(path: str) -> dict[str, str]:
    """
    解析 Cocoa .strings 文件，返回 {key: value} 字典。

    .strings 格式示例：
        /* 注释 */
        "key" = "value";
    支持 UTF-16 / UTF-8 编码。
    """
    result: dict[str, str] = {}

    for encoding in ("utf-16", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        logger.debug(f"无法解码文件：{path}")
        return result

    # 移除注释（/* ... */ 和 // ...）
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    content = re.sub(r"//[^\n]*", "", content)

    # 匹配 "key" = "value"; 模式（key 和 value 均支持转义引号）
    pattern = re.compile(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;')
    for match in pattern.finditer(content):
        key = match.group(1).replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        value = match.group(2).replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        if key and value:
            result[key] = value

    return result


# ──────────────────────────────────────────────
# .plist 文件解析
# ──────────────────────────────────────────────

def extract_strings_from_plist(data, results: set, min_length: int = 2):
    """递归遍历 plist 数据结构，提取所有字符串值。"""
    if isinstance(data, str):
        text = data.strip()
        if len(text) >= min_length and not text.startswith("{") and "\n" not in text:
            results.add(text)
    elif isinstance(data, dict):
        for v in data.values():
            extract_strings_from_plist(v, results, min_length)
    elif isinstance(data, (list, tuple)):
        for item in data:
            extract_strings_from_plist(item, results, min_length)


def parse_plist_file(path: str) -> set[str]:
    """从 .plist 文件中提取所有字符串。"""
    results: set[str] = set()
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
        extract_strings_from_plist(data, results)
    except Exception as e:
        logger.debug(f"解析 plist 失败 {path}：{e}")
    return results


# ──────────────────────────────────────────────
# 过滤规则：跳过非 UI 文本的字符串
# ──────────────────────────────────────────────

_SKIP_PATTERNS = [
    re.compile(r"^[A-Z_]{3,}$"),                  # 全大写常量
    re.compile(r"^com\.[a-z]"),                    # Bundle ID
    re.compile(r"^https?://"),                     # URL
    re.compile(r"^\d+(\.\d+)*$"),                  # 纯数字/版本号
    re.compile(r"^[0-9a-f]{8,}$", re.IGNORECASE), # 哈希值
    re.compile(r"[<>{}$]"),                        # 代码/模板语法
    re.compile(r"^NSA?|^UI|^AX"),                  # ObjC 类名
    re.compile(r"^\w+\.\w+\.\w+"),                 # 点分隔的技术标识符
]

def _should_skip(text: str) -> bool:
    """判断字符串是否应该跳过（非 UI 展示文本）。"""
    if len(text) < 2 or len(text) > 200:
        return True
    for pattern in _SKIP_PATTERNS:
        if pattern.search(text):
            return True
    # 跳过大部分字符为非 ASCII 的字符串（可能已是非英文）
    ascii_ratio = sum(1 for c in text if ord(c) < 128) / len(text)
    if ascii_ratio < 0.7:
        return True
    return False


# ──────────────────────────────────────────────
# 主提取逻辑
# ──────────────────────────────────────────────

def extract_strings(app_path: str) -> dict[str, str]:
    """
    扫描 .app 包，返回 {英文字符串: ""} 的待翻译字典。
    优先从 en.lproj 目录获取英文原文，同时也扫描所有 .strings 和 .plist 文件。
    """
    resources_path = Path(app_path) / "Contents" / "Resources"
    if not resources_path.exists():
        logger.error(f"找不到 Resources 目录：{resources_path}")
        return {}

    all_texts: set[str] = set()

    # 优先处理 en.lproj（英文本地化目录）
    en_lproj = resources_path / "en.lproj"
    if en_lproj.exists():
        for strings_file in en_lproj.glob("*.strings"):
            parsed = parse_strings_file(str(strings_file))
            all_texts.update(parsed.values())
            all_texts.update(parsed.keys())
            logger.debug(f"en.lproj: {strings_file.name}，提取 {len(parsed)} 条")

    # 扫描所有 .strings 文件
    for strings_file in resources_path.rglob("*.strings"):
        if "en.lproj" in str(strings_file):
            continue  # 已处理
        parsed = parse_strings_file(str(strings_file))
        all_texts.update(parsed.values())
        all_texts.update(parsed.keys())

    # 扫描所有 .plist 文件（排除二进制格式解析失败的）
    for plist_file in resources_path.rglob("*.plist"):
        texts = parse_plist_file(str(plist_file))
        all_texts.update(texts)

    # 过滤非 UI 文本
    filtered = {t for t in all_texts if not _should_skip(t)}
    logger.info(f"共提取 {len(all_texts)} 条字符串，过滤后保留 {len(filtered)} 条")

    return {text: "" for text in sorted(filtered)}


def merge_translations(existing: dict[str, str], new_keys: dict[str, str]) -> dict[str, str]:
    """
    合并新提取的 key 到现有翻译表。
    - 保留已有翻译（不覆盖非空值）
    - 添加新发现的 key（值为空字符串）
    - 移除不再出现的 key（可选，默认保留）
    """
    merged = dict(existing)
    added = 0
    for key in new_keys:
        if key not in merged:
            merged[key] = ""
            added += 1
    if added > 0:
        logger.info(f"新增 {added} 条待翻译字符串")
    return merged


def extract_and_save(app_path: str, output_path: str):
    """
    完整流程：提取字符串 → 合并到现有翻译表 → 保存。
    """
    if not os.path.exists(app_path):
        logger.error(f"Claude.app 不存在：{app_path}")
        logger.info("跳过提取，将使用现有翻译文件（如有）")
        return

    new_strings = extract_strings(app_path)

    # 加载已有翻译
    existing: dict[str, str] = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            logger.info(f"已加载现有翻译：{len(existing)} 条")
        except Exception as e:
            logger.warning(f"读取现有翻译失败：{e}，将覆盖")

    merged = merge_translations(existing, new_strings)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2, sort_keys=True)

    pending = sum(1 for v in merged.values() if not v)
    logger.info(
        f"翻译表已保存：{output_path}\n"
        f"  总计：{len(merged)} 条 | 已翻译：{len(merged) - pending} 条 | 待翻译：{pending} 条"
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    app_path = sys.argv[1] if len(sys.argv) > 1 else "/Applications/Claude.app"
    output = sys.argv[2] if len(sys.argv) > 2 else "translations.json"

    extract_and_save(app_path, output)
