from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .llm_adapter import LLMAdapterError, get_llm_adapter


@dataclass
class OcrImageResult:
    image_name: str
    extracted_text: str = ""
    error: str = ""


@dataclass
class OptionalOcrResult:
    status: str
    engine: str = ""
    combined_text: str = ""
    note: str = ""
    image_results: list[OcrImageResult] = field(default_factory=list)


def run_optional_ocr(image_paths: list[Path]) -> OptionalOcrResult:
    if not image_paths:
        return OptionalOcrResult(status="not_requested", note="当前草稿没有图片附件。")

    toggle = os.environ.get("TAX_INVOICE_OCR", "auto").strip().lower()
    if toggle in {"0", "off", "false", "disabled"}:
        return OptionalOcrResult(
            status="disabled",
            note="已通过环境变量关闭图片 OCR；当前只保留图片附件。",
        )

    command = _resolve_tesseract_command()
    if not command:
        fallback = _run_llm_image_ocr(image_paths, fallback_reason="未检测到 tesseract 命令")
        if fallback is not None:
            return fallback
        return OptionalOcrResult(
            status="unavailable",
            note="未检测到 tesseract 命令，且当前 LLM 图片 OCR 不可用；图片会先保留在草稿里。",
        )

    language = os.environ.get("TAX_INVOICE_TESSERACT_LANG", "chi_sim+eng").strip() or "chi_sim+eng"
    psm = os.environ.get("TAX_INVOICE_TESSERACT_PSM", "6").strip() or "6"
    image_results: list[OcrImageResult] = []
    combined_parts: list[str] = []

    with tempfile.TemporaryDirectory(prefix="tax-invoice-ocr-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        for index, image_path in enumerate(image_paths, start=1):
            prepared = temp_dir / f"ocr_{index:02d}.png"
            try:
                _prepare_image_for_ocr(image_path, prepared)
            except Exception as exc:  # pragma: no cover - defensive I/O branch
                image_results.append(OcrImageResult(image_name=image_path.name, error=f"图片预处理失败：{exc}"))
                continue

            command_parts = [
                command,
                str(prepared),
                "stdout",
                "-l",
                language,
                "--psm",
                psm,
            ]
            try:
                completed = subprocess.run(
                    command_parts,
                    capture_output=True,
                    timeout=90,
                    check=False,
                )
            except Exception as exc:  # pragma: no cover - defensive subprocess branch
                image_results.append(OcrImageResult(image_name=image_path.name, error=f"OCR 调用失败：{exc}"))
                continue

            stdout = _decode_bytes(completed.stdout).strip()
            stderr = _decode_bytes(completed.stderr).strip()

            if completed.returncode != 0:
                image_results.append(
                    OcrImageResult(
                        image_name=image_path.name,
                        error=stderr or f"OCR 退出码 {completed.returncode}",
                    )
                )
                continue

            if stdout:
                combined_parts.append(f"[{image_path.name}]\n{stdout}")
                image_results.append(OcrImageResult(image_name=image_path.name, extracted_text=stdout))
            else:
                image_results.append(OcrImageResult(image_name=image_path.name, error="OCR 已执行，但当前没有识别出稳定文本。"))

    success_count = sum(1 for item in image_results if item.extracted_text)
    if success_count == 0:
        note = "已检测到 tesseract，但当前图片没有提取出可用文本；建议继续人工补充或换更清晰截图。"
        failure_examples = [item.error for item in image_results if item.error][:1]
        if failure_examples:
            note = f"{note} 最近一次错误：{failure_examples[0]}"
        fallback = _run_llm_image_ocr(image_paths, fallback_reason=note)
        if fallback is not None:
            return fallback
        return OptionalOcrResult(
            status="empty",
            engine=f"tesseract ({language})",
            note=note,
            image_results=image_results,
        )

    status = "success" if success_count == len(image_results) else "partial"
    note = "已从图片中提取文字，结果会进入草稿解析；仍建议在复核页人工确认。"
    if status == "partial":
        note = "部分图片已提取到文字，部分仍需人工补充；草稿已保留所有附件。"
    return OptionalOcrResult(
        status=status,
        engine=f"tesseract ({language})",
        combined_text="\n\n".join(part for part in combined_parts if part.strip()),
        note=note,
        image_results=image_results,
    )


def _run_llm_image_ocr(image_paths: list[Path], *, fallback_reason: str) -> OptionalOcrResult | None:
    adapter = get_llm_adapter()
    if not adapter.is_enabled:
        return None
    image_results: list[OcrImageResult] = []
    combined_parts: list[str] = []
    errors: list[str] = []
    for image_path in image_paths:
        try:
            response = adapter.extract_text_from_image(image_path)
        except (LLMAdapterError, OSError) as exc:
            errors.append(str(exc))
            image_results.append(OcrImageResult(image_name=image_path.name, error=f"LLM 图片 OCR 失败：{exc}"))
            continue
        text = _extract_llm_ocr_text(response.parsed_json).strip()
        if text:
            combined_parts.append(f"[{image_path.name}]\n{text}")
            image_results.append(OcrImageResult(image_name=image_path.name, extracted_text=text))
        else:
            image_results.append(OcrImageResult(image_name=image_path.name, error="LLM 图片 OCR 已返回，但没有提取出稳定文本。"))
    success_count = sum(1 for item in image_results if item.extracted_text)
    if success_count == 0:
        return OptionalOcrResult(
            status="empty",
            engine=f"{adapter.provider_name} image-ocr",
            note=(
                f"{fallback_reason}；已尝试 LLM 图片 OCR，但没有提取出可用文本。"
                f" 最近一次错误：{errors[-1]}" if errors else f"{fallback_reason}；已尝试 LLM 图片 OCR，但没有提取出可用文本。"
            ),
            image_results=image_results,
        )
    status = "success" if success_count == len(image_paths) else "partial"
    return OptionalOcrResult(
        status=status,
        engine=f"{adapter.provider_name} image-ocr",
        combined_text="\n\n".join(part for part in combined_parts if part.strip()),
        note="本地 OCR 不可用或未识别出文本，已改用 LLM 图片 OCR 提取文字；仍建议在复核页人工确认。",
        image_results=image_results,
    )


def _extract_llm_ocr_text(payload: dict) -> str:
    for key in ["文字", "text", "ocr_text", "OCR文本", "内容"]:
        value = payload.get(key) if isinstance(payload, dict) else ""
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _resolve_tesseract_command() -> str:
    configured = os.environ.get("TAX_INVOICE_TESSERACT_CMD", "").strip()
    if configured:
        return configured
    for candidate in ["tesseract", "tesseract.exe"]:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return ""


def _prepare_image_for_ocr(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        processed = ImageOps.exif_transpose(image).convert("L")
        processed = ImageOps.autocontrast(processed)
        if max(processed.size) < 1800:
            processed = processed.resize((processed.width * 2, processed.height * 2))
        processed = processed.filter(ImageFilter.SHARPEN)
        processed.save(target)


def _decode_bytes(payload: bytes) -> str:
    for encoding in ["utf-8", "gb18030", "gbk"]:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")
