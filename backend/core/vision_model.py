"""
Local MobileCLIP-S0 ONNX runtime for zero-shot image/text similarity.

The model is downloaded lazily on first use. Model files are pinned to a
Hugging Face revision and the ONNX weight files are verified with SHA-256.
No model weights are committed to this repository.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Sequence

from PIL import Image, ImageOps

from config.settings import settings

logger = logging.getLogger("backend.core.vision_model")

MODEL_ID = "Xenova/mobileclip_s0"
MODEL_REVISION = "042de655852afd772a6efe57e60fa84ecfa455b2"
MODEL_NAME = "mobileclip-s0-onnx-int8-v1"
IMAGE_SIZE = 256
TEXT_CONTEXT_LENGTH = 77
LOGIT_SCALE = 100.0

_MODEL_BASE_URL = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/"
_ASSETS = {
    "vision_model_int8.onnx": (
        "onnx/vision_model_int8.onnx",
        "7a1b45f57fb9f3cde9d325759883e9451d7281336caeb9c576ae918e72080f0b",
    ),
    "text_model_int8.onnx": (
        "onnx/text_model_int8.onnx",
        "fc8d87978623385c17a46331ffb9cb5ab7fe8b61c513c094602b85f08edd0a0b",
    ),
    "tokenizer.json": ("tokenizer.json", None),
}


class VisionModelUnavailableError(RuntimeError):
    """Raised when the local ONNX vision model cannot be prepared or loaded."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MobileCLIPModel:
    """CPU-capable MobileCLIP-S0 image/text embedding model using ONNX Runtime."""

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        *,
        vision_session: Any = None,
        text_session: Any = None,
        tokenizer: Any = None,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else settings.data_dir / "models" / "mobileclip_s0"
        self._vision_session = vision_session
        self._text_session = text_session
        self._tokenizer = tokenizer
        self._text_embedding_cache: dict[str, Any] = {}
        self._load_lock = threading.RLock()
        self._cache_lock = threading.RLock()

    @staticmethod
    def preprocess_image(image: Image.Image):
        """Return a float32 NCHW tensor matching the model's 256px CLIP processor."""
        try:
            import numpy as np
        except ImportError as exc:
            raise VisionModelUnavailableError(
                "NumPy is required for local AI classification. Install project requirements."
            ) from exc

        rgb = ImageOps.exif_transpose(image).convert("RGB")
        width, height = rgb.size
        if width < 1 or height < 1:
            raise ValueError("Cannot classify an image with an empty dimension.")

        scale = IMAGE_SIZE / min(width, height)
        resized_width = max(IMAGE_SIZE, int(round(width * scale)))
        resized_height = max(IMAGE_SIZE, int(round(height * scale)))
        rgb = rgb.resize((resized_width, resized_height), Image.Resampling.BILINEAR)

        left = (rgb.width - IMAGE_SIZE) // 2
        top = (rgb.height - IMAGE_SIZE) // 2
        rgb = rgb.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))

        pixels = np.asarray(rgb, dtype=np.float32) / 255.0
        mean = np.asarray([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
        std = np.asarray([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
        pixels = (pixels - mean) / std
        return np.transpose(pixels, (2, 0, 1))[None, :, :, :].astype(np.float32, copy=False)

    def ensure_ready(self) -> Path:
        """Download/verify assets and initialize ONNX sessions; return the model cache path."""
        self._ensure_loaded()
        return self.model_dir

    def _download_asset(self, filename: str, remote_path: str, expected_sha256: Optional[str]) -> Path:
        target = self.model_dir / filename
        if target.is_file():
            if expected_sha256 is None or _sha256_file(target) == expected_sha256:
                return target
            logger.warning("Cached model asset failed SHA-256 validation; downloading again: %s", filename)
            target.unlink()

        self.model_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        url = _MODEL_BASE_URL + remote_path
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "SmartImageOrganizer/0.1"},
        )
        logger.info("Downloading MobileCLIP model asset %s from the pinned model repository.", filename)

        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)

            actual_sha256 = digest.hexdigest()
            if expected_sha256 and actual_sha256 != expected_sha256:
                temporary.unlink(missing_ok=True)
                raise VisionModelUnavailableError(
                    f"SHA-256 validation failed for {filename}; the downloaded model asset was rejected."
                )
            if filename == "tokenizer.json" and temporary.stat().st_size < 100_000:
                temporary.unlink(missing_ok=True)
                raise VisionModelUnavailableError("The downloaded tokenizer file is unexpectedly small.")
            os.replace(temporary, target)
            return target
        except VisionModelUnavailableError:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            temporary.unlink(missing_ok=True)
            raise VisionModelUnavailableError(
                "Could not download the local MobileCLIP-S0 model. Check the internet connection, "
                "then retry classification. Model files are stored locally after the first download."
            ) from exc

    def _ensure_loaded(self) -> None:
        if self._vision_session is not None and self._text_session is not None and self._tokenizer is not None:
            return

        with self._load_lock:
            if self._vision_session is not None and self._text_session is not None and self._tokenizer is not None:
                return

            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer
            except ImportError as exc:
                raise VisionModelUnavailableError(
                    "Local AI dependencies are missing. Run: python -m pip install -r requirements.txt"
                ) from exc

            vision_path = self._download_asset(*("vision_model_int8.onnx", *_ASSETS["vision_model_int8.onnx"]))
            text_path = self._download_asset(*("text_model_int8.onnx", *_ASSETS["text_model_int8.onnx"]))
            tokenizer_path = self._download_asset(*("tokenizer.json", *_ASSETS["tokenizer.json"]))

            try:
                options = ort.SessionOptions()
                options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
                options.inter_op_num_threads = 1

                self._vision_session = self._vision_session or ort.InferenceSession(
                    str(vision_path), sess_options=options, providers=["CPUExecutionProvider"]
                )
                self._text_session = self._text_session or ort.InferenceSession(
                    str(text_path), sess_options=options, providers=["CPUExecutionProvider"]
                )
                self._tokenizer = self._tokenizer or Tokenizer.from_file(str(tokenizer_path))
                self._tokenizer.enable_truncation(max_length=TEXT_CONTEXT_LENGTH)
                self._tokenizer.enable_padding(
                    length=TEXT_CONTEXT_LENGTH,
                    pad_id=49407,
                    pad_token="<|endoftext|>",
                )
            except Exception as exc:
                self._vision_session = None
                self._text_session = None
                self._tokenizer = None
                raise VisionModelUnavailableError(
                    "MobileCLIP-S0 model assets were downloaded, but ONNX Runtime could not initialize them. "
                    "Check the model cache and installed dependency versions."
                ) from exc

    @staticmethod
    def _normalise_embeddings(values):
        import numpy as np

        embeddings = np.asarray(values, dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=-1, keepdims=True)
        return np.divide(embeddings, norms, out=np.zeros_like(embeddings), where=norms > 1e-12)

    @staticmethod
    def _run_embedding(session: Any, feeds: dict[str, Any], preferred_name: str):
        output_meta = session.get_outputs()
        output_name = next(
            (item.name for item in output_meta if preferred_name in item.name.lower()),
            output_meta[0].name,
        )
        return session.run([output_name], feeds)[0]

    @staticmethod
    def _make_text_feeds(session: Any, input_ids, attention_mask) -> dict[str, Any]:
        import numpy as np

        feeds: dict[str, Any] = {}
        positions = np.broadcast_to(
            np.arange(input_ids.shape[1], dtype=np.int64),
            input_ids.shape,
        )
        for index, item in enumerate(session.get_inputs()):
            name = item.name.lower()
            if "input_ids" in name or (index == 0 and name in {"input", "input_0"}):
                feeds[item.name] = input_ids
            elif "attention_mask" in name:
                feeds[item.name] = attention_mask
            elif "position_ids" in name:
                feeds[item.name] = positions
            elif "token_type_ids" in name:
                feeds[item.name] = np.zeros_like(input_ids)
            else:
                raise VisionModelUnavailableError(
                    f"Unsupported MobileCLIP text-model input: {item.name}"
                )
        return feeds

    @staticmethod
    def _make_vision_feeds(session: Any, pixel_values) -> dict[str, Any]:
        feeds: dict[str, Any] = {}
        for index, item in enumerate(session.get_inputs()):
            name = item.name.lower()
            if "pixel" in name or "image" in name or (index == 0 and name in {"input", "input_0"}):
                feeds[item.name] = pixel_values
            else:
                raise VisionModelUnavailableError(
                    f"Unsupported MobileCLIP vision-model input: {item.name}"
                )
        return feeds

    def _encode_texts(self, prompts: Sequence[str]):
        import numpy as np

        self._ensure_loaded()
        unique_missing = []
        with self._cache_lock:
            for prompt in prompts:
                if prompt not in self._text_embedding_cache and prompt not in unique_missing:
                    unique_missing.append(prompt)

        if unique_missing:
            for start in range(0, len(unique_missing), 32):
                batch = unique_missing[start : start + 32]
                encodings = self._tokenizer.encode_batch(batch)
                input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
                attention_mask = np.asarray([encoding.attention_mask for encoding in encodings], dtype=np.int64)
                feeds = self._make_text_feeds(self._text_session, input_ids, attention_mask)
                output = self._run_embedding(self._text_session, feeds, "text_embeds")
                normalised = self._normalise_embeddings(output)
                with self._cache_lock:
                    for prompt, embedding in zip(batch, normalised):
                        self._text_embedding_cache[prompt] = embedding.copy()

        with self._cache_lock:
            return np.asarray([self._text_embedding_cache[prompt] for prompt in prompts], dtype=np.float32)

    def score_texts(self, image: Image.Image, prompts: Sequence[str]) -> list[float]:
        """Return cosine similarity between image pixels and each natural-language prompt."""
        import numpy as np

        if not prompts:
            return []
        self._ensure_loaded()
        pixels = self.preprocess_image(image)
        feeds = self._make_vision_feeds(self._vision_session, pixels)
        image_embedding = self._normalise_embeddings(
            self._run_embedding(self._vision_session, feeds, "image_embeds")
        ).reshape(-1)
        text_embeddings = self._encode_texts(prompts)
        scores = np.matmul(text_embeddings, image_embedding)
        return [float(value) for value in scores.tolist()]
