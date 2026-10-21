"""
Local MobileCLIP-S0 zero-shot image classifier.

Categories and fine-grained semantic labels are selected by comparing the actual
image embedding with text-prompt embeddings from a pretrained vision-language
model. Descriptions are selected labels, not free-form generated captions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

from config.settings import settings
from backend.db.session import db_session
from backend.db import repository
from backend.core.renamer import generate_semantic_filename
from backend.core.vision_model import (
    LOGIT_SCALE,
    MODEL_NAME,
    MobileCLIPModel,
    VisionModelUnavailableError,
)

logger = logging.getLogger("backend.core.classifier")

SUBCATEGORY_MAP: Dict[str, List[str]] = {
    "animals_nature": ["Landscapes", "Wildlife_Pets", "Plants_Flowers"],
    "documents_scans": ["Scanned_Documents", "Receipts_Invoices", "Forms_Letters"],
    "screenshots_ui": ["Desktop_UI", "Mobile_Screenshots", "App_Interfaces"],
    "people_portraits": ["Portraits", "Group_Photos", "Candid"],
    "food_cooking": ["Plated_Meals", "Baking_Desserts", "Beverages"],
    "products_ecommerce": ["Packaged_Goods", "Merchandise", "Retail_Items"],
    "places_travel": ["Architecture", "Cityscapes", "Landmarks"],
    "graphics_illustrations": ["Vector_Art", "Digital_Drawings", "Clip_Art"],
    "ai_covers_thumbnails": ["Digital_Artwork", "Thumbnails"],
    "social_media_designs": ["Banners", "Story_Templates"],
    "logos_icons": ["Logos", "App_Icons"],
    "memes_quotes": ["Memes", "Quotes_Typography"],
    "other": ["General"],
}

# Each candidate includes a prompt for the pretrained model, a conservative
# human-readable label for the filename, and its destination subcategory.
# These are intentionally curated labels, not claims of free-form captioning.
VISUAL_PROMPTS: Dict[str, List[Tuple[str, str, str]]] = {
    "animals_nature": [
        ("a photograph of a dog or puppy outdoors", "dog outdoors", "Wildlife_Pets"),
        ("a photograph of a cat", "cat portrait", "Wildlife_Pets"),
        ("a photograph of a bird in nature", "bird outdoors", "Wildlife_Pets"),
        ("a photograph of a wild animal", "wildlife photograph", "Wildlife_Pets"),
        ("a scenic mountain lake landscape", "mountain lake landscape", "Landscapes"),
        ("a photograph of a green forest and trees", "green forest landscape", "Landscapes"),
        ("a photograph of a beach and ocean", "beach ocean landscape", "Landscapes"),
        ("a close-up photograph of flowers and plants", "flowers and plants", "Plants_Flowers"),
        ("a photograph of green grass and foliage", "green foliage outdoors", "Plants_Flowers"),
    ],
    "documents_scans": [
        ("a scanned paper document with printed text", "scanned paper document", "Scanned_Documents"),
        ("a printed receipt or invoice with item lines", "receipt invoice document", "Receipts_Invoices"),
        ("a filled paper form or official letter", "paper form letter", "Forms_Letters"),
        ("handwritten notes on paper", "handwritten notes", "Scanned_Documents"),
        ("a page from a printed book", "printed book page", "Scanned_Documents"),
    ],
    "screenshots_ui": [
        ("a computer terminal or code editor showing source code and logs", "terminal code screenshot", "Desktop_UI"),
        ("a desktop software application user interface", "desktop software screenshot", "Desktop_UI"),
        ("a smartphone mobile application screenshot", "mobile app screenshot", "Mobile_Screenshots"),
        ("a website displayed in a browser window", "website interface screenshot", "App_Interfaces"),
        ("a software dashboard with charts and panels", "software dashboard screenshot", "App_Interfaces"),
    ],
    "people_portraits": [
        ("a close-up portrait photograph of one person", "person portrait", "Portraits"),
        ("a family or group photograph with several people", "family group photo", "Group_Photos"),
        ("a wedding couple portrait", "wedding couple portrait", "Portraits"),
        ("a candid photograph of people interacting", "candid people photo", "Candid"),
    ],
    "food_cooking": [
        ("a plated cooked meal on a dining plate", "plated food meal", "Plated_Meals"),
        ("a chocolate cake pastry or dessert", "chocolate cake dessert", "Baking_Desserts"),
        ("a cup of coffee tea or another beverage", "coffee tea beverage", "Beverages"),
        ("fresh fruit and vegetables arranged as food", "fresh fruits vegetables", "Plated_Meals"),
        ("a close-up photograph of bread or baked goods", "bread baked goods", "Baking_Desserts"),
    ],
    "products_ecommerce": [
        ("an electronic product such as a phone headphones or computer accessory", "electronic product", "Merchandise"),
        ("a cosmetic skincare or beauty product", "cosmetic beauty product", "Packaged_Goods"),
        ("clothing shoes or a fashion accessory for sale", "clothing fashion product", "Merchandise"),
        ("a packaged retail product photographed on a plain background", "packaged retail product", "Packaged_Goods"),
        ("a furniture or home decor product", "home decor product", "Retail_Items"),
    ],
    "places_travel": [
        ("a photograph of a building or architectural facade", "building architecture", "Architecture"),
        ("a city skyline with multiple buildings", "city skyline", "Cityscapes"),
        ("a famous landmark or tourist attraction", "travel landmark", "Landmarks"),
        ("a street scene in a town or city", "city street scene", "Cityscapes"),
        ("a photograph of an interior room or building interior", "building interior", "Architecture"),
    ],
    "graphics_illustrations": [
        ("a flat vector illustration or clip art graphic", "vector illustration", "Vector_Art"),
        ("a digital drawing or cartoon illustration", "digital cartoon illustration", "Digital_Drawings"),
        ("a colorful 3D rendered digital artwork", "3d digital artwork", "Digital_Drawings"),
        ("an infographic with icons labels and diagrams", "informational infographic", "Clip_Art"),
    ],
    "ai_covers_thumbnails": [
        ("a dramatic technology news cover or YouTube thumbnail", "technology news thumbnail", "Thumbnails"),
        ("a futuristic AI robot or artificial intelligence concept artwork", "futuristic AI artwork", "Digital_Artwork"),
        ("a dramatic video cover with a person and bold headline", "video cover thumbnail", "Thumbnails"),
    ],
    "social_media_designs": [
        ("a promotional social media post design", "social media promotional post", "Banners"),
        ("an Instagram story template or vertical social media graphic", "vertical story design", "Story_Templates"),
        ("a marketing banner with headline and graphic elements", "marketing banner design", "Banners"),
        ("an event poster or promotional flyer", "event poster flyer", "Banners"),
    ],
    "logos_icons": [
        ("a company brand logo or wordmark", "brand logo", "Logos"),
        ("a mobile app icon on a simple background", "mobile app icon", "App_Icons"),
        ("a minimalist symbol or pictogram icon", "minimalist icon", "App_Icons"),
    ],
    "memes_quotes": [
        ("an internet meme image with a humorous caption", "captioned internet meme", "Memes"),
        ("a typography graphic displaying a quote", "quote typography graphic", "Quotes_Typography"),
        ("an inspirational quote rendered as text on a background", "inspirational quote graphic", "Quotes_Typography"),
    ],
    "other": [
        ("an abstract artwork with shapes and colors", "abstract artwork", "General"),
        ("a general photograph that does not clearly fit another category", "general photograph", "General"),
    ],
}


@dataclass
class ClassificationResult:
    category_id: int
    category_code: str
    category_name: str
    subcategory: str
    confidence: float
    margin: float
    status: str
    reason: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    raw_scores: Dict[str, float] = field(default_factory=dict)
    visual_description: str = ""
    proposed_filename: str = ""


def _softmax(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    scaled = [float(value) * LOGIT_SCALE for value in values]
    maximum = max(scaled)
    exponentials = [__import__("math").exp(value - maximum) for value in scaled]
    total = sum(exponentials) or 1.0
    return [value / total for value in exponentials]


class LocalVisionClassifier:
    """
    Zero-shot local vision-language classifier.

    MobileCLIP-S0 runs locally with ONNX Runtime on CPU. It compares image
    embeddings with the configured category prompts and a small set of
    fine-grained prompts to propose a category and descriptive filename.
    """

    def __init__(
        self,
        high_confidence_threshold: float = 0.65,
        min_margin: float = 0.15,
        model: Optional[Any] = None,
    ):
        self.high_confidence_threshold = high_confidence_threshold
        self.min_margin = min_margin
        self.categories: List[Dict[str, Any]] = []
        self.model = model if model is not None else MobileCLIPModel()
        self._load_categories()

    def _load_categories(self, db_path: Optional[Path] = None) -> None:
        """Load the active category taxonomy from SQLite or settings fallback."""
        try:
            with db_session(db_path) as conn:
                db_categories = repository.get_categories(conn)
                if db_categories:
                    self.categories = db_categories
                    return
        except Exception as exc:
            logger.debug("Could not load categories from the default database: %s", exc)

        self.categories = [
            {
                "id": index + 1,
                "code_name": category.code_name,
                "display_name": category.display_name,
                "description": category.description,
                "text_prompt": category.text_prompt,
            }
            for index, category in enumerate(settings.categories)
        ]

    @staticmethod
    def _fallback_description(category: Dict[str, Any]) -> Tuple[str, str]:
        code = category["code_name"]
        subcategories = SUBCATEGORY_MAP.get(code, ["General"])
        label = category.get("display_name", code.replace("_", " ")).lower()
        return f"{label} image", subcategories[0]

    def _select_visual_label(
        self,
        image: Image.Image,
        category: Dict[str, Any],
    ) -> Tuple[str, str]:
        candidates = VISUAL_PROMPTS.get(category["code_name"], [])
        if not candidates:
            return self._fallback_description(category)

        prompts = [candidate[0] for candidate in candidates]
        similarities = self.model.score_texts(image, prompts)
        ranked = sorted(
            zip(candidates, similarities),
            key=lambda item: item[1],
            reverse=True,
        )
        best_candidate, best_similarity = ranked[0]
        second_similarity = ranked[1][1] if len(ranked) > 1 else -1.0

        # Avoid overly specific labels when the visual-language match is weak.
        if best_similarity < 0.15 or (best_similarity - second_similarity) < 0.01:
            return self._fallback_description(category)

        return best_candidate[1], best_candidate[2]

    def classify_single_image(
        self,
        image_path: Path,
        original_filename: Optional[str] = None,
    ) -> ClassificationResult:
        """Analyze actual image pixels using MobileCLIP and propose a safe filename."""
        if not self.categories:
            self._load_categories()
        if not self.categories:
            raise RuntimeError("No image categories are configured in config/categories.yaml.")

        source_name = original_filename or image_path.name
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGB").copy()
        except Exception as exc:
            logger.warning("Cannot decode image %s for AI classification: %s", image_path, exc)
            fallback = next(
                (category for category in self.categories if category["code_name"] == "other"),
                self.categories[-1],
            )
            proposed = generate_semantic_filename(
                description="unreadable image file",
                original_filename=source_name,
                category_name=fallback["display_name"],
                subcategory="General",
            )
            return ClassificationResult(
                category_id=fallback["id"],
                category_code=fallback["code_name"],
                category_name=fallback["display_name"],
                subcategory="General",
                confidence=0.0,
                margin=0.0,
                status="needs_review",
                reason="image_decode_error",
                tags=[fallback["code_name"]],
                raw_scores={},
                visual_description="image could not be decoded",
                proposed_filename=proposed,
            )

        category_prompts = [
            str(category.get("text_prompt") or category.get("description") or category["display_name"])
            for category in self.categories
        ]
        similarities = self.model.score_texts(image, category_prompts)
        if len(similarities) != len(self.categories):
            raise RuntimeError("The vision model returned an unexpected number of category scores.")

        probabilities = _softmax(similarities)
        ranked_indices = sorted(
            range(len(self.categories)),
            key=lambda index: similarities[index],
            reverse=True,
        )
        best_index = ranked_indices[0]
        second_index = ranked_indices[1] if len(ranked_indices) > 1 else best_index
        best_category = self.categories[best_index]
        confidence = probabilities[best_index]
        margin = confidence - probabilities[second_index]
        best_similarity = similarities[best_index]

        if best_similarity < 0.15:
            status, reason = "needs_review", "low_similarity"
        elif confidence < self.high_confidence_threshold:
            status, reason = "needs_review", "low_confidence"
        elif margin < self.min_margin:
            status, reason = "needs_review", "ambiguous_margin"
        else:
            status, reason = "classified", None

        visual_description, subcategory = self._select_visual_label(image, best_category)
        proposed_filename = generate_semantic_filename(
            description=visual_description,
            original_filename=source_name,
            category_name=best_category["display_name"],
            subcategory=subcategory,
        )

        ranked_categories = sorted(
            zip(self.categories, probabilities),
            key=lambda item: item[1],
            reverse=True,
        )
        raw_scores = {
            category["code_name"]: round(probability, 4)
            for category, probability in ranked_categories[:5]
        }
        tags = [best_category["code_name"], subcategory]
        tags.extend(
            word for word in visual_description.split()
            if len(word) > 3 and word not in tags
        )

        return ClassificationResult(
            category_id=best_category["id"],
            category_code=best_category["code_name"],
            category_name=best_category["display_name"],
            subcategory=subcategory,
            confidence=round(float(confidence), 4),
            margin=round(float(margin), 4),
            status=status,
            reason=reason,
            tags=tags,
            raw_scores=raw_scores,
            visual_description=visual_description,
            proposed_filename=proposed_filename,
        )

    def classify_catalog(
        self,
        db_path: Optional[Path] = None,
        batch_size: int = 50,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, int]:
        """
        Classify images not yet processed by this model version.

        Older heuristic-generated classifications are eligible for reprocessing.
        Approved/organized images are left alone, and filenames explicitly edited
        by a user are preserved.
        """
        self._load_categories(db_path)
        if not settings.enable_local_ai and self.model.__class__ is MobileCLIPModel:
            raise VisionModelUnavailableError("Local AI is disabled by ENABLE_LOCAL_AI=false.")
        total_processed = 0
        classified_count = 0
        needs_review_count = 0

        with db_session(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT i.id, i.file_path, i.file_name, i.thumbnail_path, i.status,
                       i.proposed_filename, i.visual_description, i.filename_is_manual
                FROM images AS i
                WHERE i.status IN ('scanned', 'needs_review', 'classified')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM image_classifications AS c
                      WHERE c.image_id = i.id
                        AND c.provider = 'local_mobileclip'
                        AND c.model_name = ?
                  )
                ORDER BY i.id ASC
                """,
                (MODEL_NAME,),
            )
            rows = [dict(row) for row in cursor.fetchall()]

            for item in rows:
                image_id = item["id"]
                source_path = Path(item["file_path"])
                thumbnail_path = Path(item["thumbnail_path"]) if item.get("thumbnail_path") else None
                evaluation_path = (
                    thumbnail_path
                    if thumbnail_path is not None and thumbnail_path.is_file()
                    else source_path
                )
                if not evaluation_path.is_file():
                    logger.warning("Skipping missing image during classification: %s", source_path)
                    continue

                result = self.classify_single_image(
                    evaluation_path,
                    original_filename=item["file_name"],
                )

                cursor.execute(
                    """
                    INSERT INTO image_classifications (
                        image_id, provider, model_name, predicted_category_id,
                        confidence_score, margin_score, raw_scores_json, suggested_tags_json
                    ) VALUES (?, 'local_mobileclip', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        image_id,
                        MODEL_NAME,
                        result.category_id,
                        result.confidence,
                        result.margin,
                        json.dumps(result.raw_scores),
                        json.dumps(result.tags),
                    ),
                )

                if result.status == "needs_review":
                    cursor.execute(
                        """
                        INSERT INTO review_queue (image_id, reason, is_resolved)
                        SELECT ?, ?, 0
                        WHERE NOT EXISTS (
                            SELECT 1 FROM review_queue
                            WHERE image_id = ? AND is_resolved = 0
                        )
                        """,
                        (image_id, result.reason or "low_confidence", image_id),
                    )
                    needs_review_count += 1
                else:
                    classified_count += 1
                    # Close stale model-generated review items when a newer model
                    # version now classifies the image with sufficient confidence.
                    cursor.execute(
                        """
                        UPDATE review_queue
                        SET is_resolved = 1, resolved_at = DATETIME('now')
                        WHERE image_id = ? AND is_resolved = 0
                          AND reason IN ('low_confidence', 'ambiguous_margin', 'low_similarity')
                        """,
                        (image_id,),
                    )

                proposed_filename = (
                    item["proposed_filename"]
                    if item.get("filename_is_manual") and item.get("proposed_filename")
                    else result.proposed_filename
                )
                cursor.execute(
                    """
                    UPDATE images
                    SET status = ?,
                        primary_category_id = ?,
                        proposed_filename = ?,
                        visual_description = ?,
                        updated_at = DATETIME('now')
                    WHERE id = ?
                    """,
                    (
                        result.status,
                        result.category_id,
                        proposed_filename,
                        result.visual_description,
                        image_id,
                    ),
                )

                total_processed += 1
                if progress_callback:
                    progress_callback({
                        "processed": total_processed,
                        "total": len(rows),
                        "current_file": item["file_name"],
                    })

        return {
            "total_processed": total_processed,
            "classified_count": classified_count,
            "needs_review_count": needs_review_count,
        }
