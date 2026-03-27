"""
translator.py — 使用 Claude API 批量翻译 UI 字符串

从 translations.json 读取值为空字符串的条目，
每批 50 个发送给 Claude API，将翻译结果写回文件。
"""

import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 指数退避基础延迟（秒）


def _call_claude_api(client, items: list[str], target_language: str = "zh-CN") -> Optional[dict[str, str]]:
    """
    调用 Claude API 翻译一批字符串。
    返回 {英文: 译文} 字典，失败时返回 None。
    """
    lang_name = {"zh-CN": "简体中文", "zh-TW": "繁体中文", "ja": "日语", "ko": "韩语"}.get(
        target_language, target_language
    )

    prompt = (
        f"请将以下 macOS 应用的 UI 界面文本翻译成{lang_name}。\n"
        "翻译要求：\n"
        "- 简洁自然，符合 macOS 用语习惯\n"
        "- 按钮、菜单等控件文字要简短\n"
        "- 保留专有名词（如 Claude、API、Markdown 等）不翻译\n"
        "- 严格以 JSON 格式返回，key 为原英文，value 为译文\n"
        "- 不要添加任何额外说明文字，只返回 JSON\n\n"
        f"待翻译文本列表：\n{json.dumps(items, ensure_ascii=False, indent=2)}"
    )

    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text.strip()

        # 提取 JSON 部分（防止模型在 JSON 前后添加了说明文字）
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            logger.warning("API 返回内容不包含 JSON")
            return None

        result = json.loads(response_text[json_start:json_end])
        if not isinstance(result, dict):
            logger.warning("API 返回的 JSON 不是对象格式")
            return None

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败：{e}")
        return None
    except Exception as e:
        logger.warning(f"API 调用失败：{e}")
        return None


def translate_batch(
    client,
    items: list[str],
    target_language: str = "zh-CN",
) -> dict[str, str]:
    """
    翻译一批字符串，带指数退避重试。
    返回成功翻译的 {英文: 译文} 字典（可能少于输入数量）。
    """
    for attempt in range(1, MAX_RETRIES + 1):
        result = _call_claude_api(client, items, target_language)
        if result is not None:
            # 过滤掉值为空或与原文相同的翻译（视为未翻译）
            valid = {k: v for k, v in result.items() if v and v != k}
            logger.debug(f"批次翻译：{len(items)} 条输入，{len(valid)} 条成功")
            return valid

        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(f"第 {attempt} 次尝试失败，{delay:.0f}s 后重试...")
            time.sleep(delay)

    logger.error(f"批次翻译失败（已重试 {MAX_RETRIES} 次），跳过本批次")
    return {}


def translate_all_pending(
    translations_file: str,
    api_key: str,
    target_language: str = "zh-CN",
    batch_size: int = BATCH_SIZE,
):
    """
    翻译 translations.json 中所有值为空字符串的条目。
    每完成一批立即写回文件，避免中途失败丢失进度。
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic 库未安装，请运行：pip install anthropic")
        return

    if not os.path.exists(translations_file):
        logger.error(f"翻译文件不存在：{translations_file}")
        return

    with open(translations_file, "r", encoding="utf-8") as f:
        translations: dict[str, str] = json.load(f)

    pending_keys = [k for k, v in translations.items() if not v]
    if not pending_keys:
        logger.info("没有待翻译的条目")
        return

    logger.info(f"开始翻译 {len(pending_keys)} 条字符串（批次大小：{batch_size}）")

    client = anthropic.Anthropic(api_key=api_key)
    translated_count = 0
    failed_count = 0

    for i in range(0, len(pending_keys), batch_size):
        batch = pending_keys[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(pending_keys) + batch_size - 1) // batch_size

        logger.info(f"批次 {batch_num}/{total_batches}（{len(batch)} 条）...")

        results = translate_batch(client, batch, target_language)

        if results:
            translations.update(results)
            translated_count += len(results)
            failed_count += len(batch) - len(results)

            # 立即写回文件保存进度
            with open(translations_file, "w", encoding="utf-8") as f:
                json.dump(translations, f, ensure_ascii=False, indent=2, sort_keys=True)
        else:
            failed_count += len(batch)

        # 批次间短暂等待，避免触发 rate limit
        if i + batch_size < len(pending_keys):
            time.sleep(0.5)

    logger.info(
        f"翻译完成：成功 {translated_count} 条，失败/跳过 {failed_count} 条\n"
        f"结果已保存到：{translations_file}"
    )

    if failed_count > 0:
        logger.info(
            f"提示：{failed_count} 条未能翻译，可手工编辑 {translations_file} 补充"
        )


def review_translations(translations_file: str):
    """打印翻译统计信息，便于用户审核。"""
    if not os.path.exists(translations_file):
        print(f"文件不存在：{translations_file}")
        return

    with open(translations_file, "r", encoding="utf-8") as f:
        translations = json.load(f)

    total = len(translations)
    translated = sum(1 for v in translations.values() if v)
    pending = total - translated

    print(f"\n=== 翻译统计 ===")
    print(f"总计：{total} 条")
    print(f"已翻译：{translated} 条 ({translated/total*100:.1f}%)")
    print(f"待翻译：{pending} 条")

    if pending > 0:
        print(f"\n待翻译条目（前 10 条）：")
        count = 0
        for k, v in translations.items():
            if not v:
                print(f"  {repr(k)}")
                count += 1
                if count >= 10:
                    if pending > 10:
                        print(f"  ... 及另外 {pending - 10} 条")
                    break


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 2:
        print("用法：")
        print("  python translator.py translate [api_key] [translations.json]")
        print("  python translator.py review [translations.json]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "translate":
        api_key = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("请提供 API Key：python translator.py translate <api_key>")
            sys.exit(1)
        translations_path = sys.argv[3] if len(sys.argv) > 3 else "translations.json"
        translate_all_pending(translations_path, api_key)

    elif command == "review":
        translations_path = sys.argv[2] if len(sys.argv) > 2 else "translations.json"
        review_translations(translations_path)

    else:
        print(f"未知命令：{command}")
        sys.exit(1)
