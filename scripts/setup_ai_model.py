"""Download and initialize the pinned local MobileCLIP-S0 ONNX model."""

from backend.core.vision_model import MODEL_ID, MODEL_NAME, MODEL_REVISION, MobileCLIPModel


def main() -> int:
    model = MobileCLIPModel()
    try:
        cache_path = model.ensure_ready()
    except Exception as exc:
        print(f"AI model setup failed: {exc}")
        return 1

    print("Local vision model is ready.")
    print(f"Model: {MODEL_ID}")
    print(f"Revision: {MODEL_REVISION}")
    print(f"Runtime: {MODEL_NAME}")
    print(f"Cache: {cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
