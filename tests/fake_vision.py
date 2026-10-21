"""Deterministic test double for the real MobileCLIP vision-language model."""

from PIL import Image, ImageStat


class FakeVisionModel:
    """Scores prompts predictably from synthetic test images; never used in production."""

    @staticmethod
    def _kind(image: Image.Image) -> str:
        rgb = image.convert("RGB")
        width, height = rgb.size
        stats = ImageStat.Stat(rgb)
        red, green, blue = stats.mean[:3]
        brightness = (red + green + blue) / (3 * 255)

        if width > height * 1.2:
            top = rgb.crop((0, 0, width, max(1, height // 3)))
            bottom = rgb.crop((0, max(0, height * 2 // 3), width, height))
            top_blue = ImageStat.Stat(top).mean[2]
            bottom_green = ImageStat.Stat(bottom).mean[1]
            if top_blue > 120 and bottom_green > 90 and top_blue > ImageStat.Stat(top).mean[0]:
                return "nature"
            if brightness < 0.35:
                return "screenshot"

        if height > width * 1.1 and brightness > 0.65:
            return "document"

        if width == height:
            center = rgb.getpixel((width // 2, height // 2))
            if center[0] > center[1] + 25 and center[0] > center[2] + 25:
                return "food"
            if brightness > 0.82:
                return "document"

        if brightness < 0.35:
            return "screenshot"
        return "other"

    @staticmethod
    def _match_score(kind: str, prompt: str) -> float:
        text = prompt.lower()
        if kind == "document":
            if "scanned paper document" in text:
                return 0.44
            if any(word in text for word in ("document", "receipt", "invoice", "paper", "form", "handwritten", "book page")):
                return 0.34
        elif kind == "nature":
            if "mountain lake" in text:
                return 0.46
            if any(word in text for word in ("natural landscape", "mountain", "forest", "flowers", "plants", "dog", "cat", "bird", "wild animal", "beach and ocean", "green grass")):
                return 0.35
        elif kind == "screenshot":
            if "terminal or code editor" in text:
                return 0.46
            if any(word in text for word in ("screenshot", "user interface", "terminal", "code editor", "browser window", "dashboard")):
                return 0.35
        elif kind == "food":
            if "chocolate cake" in text:
                return 0.46
            if any(word in text for word in ("food dish", "meal", "cake", "dessert", "beverage", "coffee", "fruit", "baked goods")):
                return 0.34
        return 0.14

    def score_texts(self, image: Image.Image, prompts):
        kind = self._kind(image)
        return [self._match_score(kind, prompt) for prompt in prompts]
