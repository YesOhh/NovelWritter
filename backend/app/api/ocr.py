"""OCR 图片识别 API：上传一张或多张图片，识别为文本。"""
import base64
import binascii

from fastapi import APIRouter, HTTPException

from app.llm.claude_client import ocr_images
from app.schemas import OcrRequest, OcrResult

router = APIRouter(prefix="/api", tags=["ocr"])

# Anthropic 视觉支持的图片格式。
_SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# 单张图片解码后体积上限（5MB），避免超出模型限制。
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _normalize_image(media_type: str, data: str) -> dict:
    media_type = media_type.strip().lower()
    if media_type == "image/jpg":
        media_type = "image/jpeg"
    if media_type not in _SUPPORTED_MEDIA_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式：{media_type}，仅支持 JPEG/PNG/GIF/WebP。",
        )
    # 去掉可能存在的 data URL 前缀。
    payload = data.split(",", 1)[1] if data.startswith("data:") else data
    payload = payload.strip()
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="图片 base64 数据无法解码。")
    if not raw:
        raise HTTPException(status_code=400, detail="图片内容为空。")
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="单张图片超过 5MB，请压缩后再试。")
    return {"media_type": media_type, "data": payload}


@router.post("/ocr", response_model=OcrResult)
async def recognize_images(body: OcrRequest) -> OcrResult:
    """将上传的图片识别为文本（基于 Claude 视觉能力）。"""
    images = [_normalize_image(img.media_type, img.data) for img in body.images]
    try:
        text = await ocr_images(images, instruction=body.instruction, model=body.model)
    except Exception as exc:  # noqa: BLE001 - 统一转成 502 反馈给前端
        raise HTTPException(status_code=502, detail=f"OCR 识别失败：{exc}") from exc
    return OcrResult(text=text, image_count=len(images))
