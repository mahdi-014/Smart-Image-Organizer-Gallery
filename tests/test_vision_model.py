from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from backend.core.vision_model import MobileCLIPModel, MODEL_ID, MODEL_REVISION


class FakeTokenizer:
    def enable_truncation(self, **kwargs):
        self.truncation = kwargs

    def enable_padding(self, **kwargs):
        self.padding = kwargs

    def encode_batch(self, prompts):
        encodings = []
        for prompt in prompts:
            first_id = 10 if "first" in prompt else 20
            ids = [first_id] + [0] * 76
            mask = [1] + [0] * 76
            encodings.append(SimpleNamespace(ids=ids, attention_mask=mask))
        return encodings


class FakeSession:
    def __init__(self, inputs, outputs, result):
        self._inputs = [SimpleNamespace(name=name) for name in inputs]
        self._outputs = [SimpleNamespace(name=name) for name in outputs]
        self._result = result

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def run(self, output_names, feeds):
        self.last_feeds = feeds
        if "pixel_values" in feeds:
            return [np.asarray([[3.0, 4.0]], dtype=np.float32)]
        ids = feeds["input_ids"][:, 0]
        vectors = [
            [1.0, 0.0] if token_id == 10 else [0.0, 1.0]
            for token_id in ids
        ]
        return [np.asarray(vectors, dtype=np.float32)]


def test_model_uses_pinned_mobileclip_s0_revision():
    assert MODEL_ID == "Xenova/mobileclip_s0"
    assert len(MODEL_REVISION) == 40


def test_constructor_does_not_download_model_or_create_directories(tmp_path):
    model_dir = tmp_path / "model-cache"
    MobileCLIPModel(model_dir=model_dir)
    assert not model_dir.exists()


def test_preprocess_image_returns_rgb_nchw_float_tensor():
    image = Image.new("RGBA", (80, 120), (255, 0, 0, 100))
    tensor = MobileCLIPModel.preprocess_image(image)
    assert tensor.shape == (1, 3, 256, 256)
    assert tensor.dtype == np.float32
    assert float(tensor.min()) >= 0.0
    assert float(tensor.max()) <= 1.0


def test_score_texts_uses_onnx_embeddings_and_cosine_similarity(tmp_path):
    vision = FakeSession(["pixel_values"], ["image_embeds"], None)
    text = FakeSession(["input_ids", "attention_mask"], ["text_embeds"], None)
    model = MobileCLIPModel(
        model_dir=tmp_path / "unused-cache",
        vision_session=vision,
        text_session=text,
        tokenizer=FakeTokenizer(),
    )

    scores = model.score_texts(Image.new("RGB", (256, 256), "white"), ["first prompt", "second prompt"])

    # Image [3, 4] normalizes to [0.6, 0.8]; the two text vectors are unit axes.
    assert scores == pytest.approx([0.6, 0.8])
    assert set(vision.last_feeds) == {"pixel_values"}
    assert set(text.last_feeds) == {"input_ids", "attention_mask"}
    assert text.last_feeds["input_ids"].shape == (2, 77)
    assert text.last_feeds["attention_mask"].shape == (2, 77)


def test_score_texts_returns_empty_for_empty_prompt_list(tmp_path):
    model = MobileCLIPModel(model_dir=tmp_path / "unused-cache")
    assert model.score_texts(Image.new("RGB", (10, 10)), []) == []
