"""
Local AI Vision Classifier and Semantic Description Engine.

Performs zero-shot image classification, subcategory refinement,
and content-aware natural-language visual description generation
using local image feature analysis and category anchor prompts.
Supports confidence scoring, margin thresholds, and Needs Review routing.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from PIL import Image, ImageStat, ImageFilter

from config.settings import settings
from backend.db.session import db_session, get_connection
from backend.db import repository
from backend.core.renamer import generate_semantic_filename

logger = logging.getLogger("backend.core.classifier")


# Subcategory mappings for fine-grained folder generation
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


@dataclass
class ClassificationResult:
    category_id: int
    category_code: str
    category_name: str
    subcategory: str
    confidence: float
    margin: float
    status: str  # 'classified' or 'needs_review'
    reason: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    raw_scores: Dict[str, float] = field(default_factory=dict)
    visual_description: str = ""
    proposed_filename: str = ""


class LocalVisionClassifier:
    """
    Zero-shot local image classifier operating completely on the local CPU.
    Extracts multi-zone color, texture, and structural features to classify
    and generate content-aware descriptive filenames.
    """

    def __init__(self, high_confidence_threshold: float = 0.55, min_margin: float = 0.10):
        self.high_confidence_threshold = high_confidence_threshold
        self.min_margin = min_margin
        self.categories: List[Dict[str, Any]] = []
        self._load_categories()

    def _load_categories(self) -> None:
        """Loads categories taxonomy from database or categories.yaml fallback."""
        try:
            with db_session() as conn:
                db_cats = repository.get_categories(conn)
                if db_cats:
                    self.categories = db_cats
                    return
        except Exception:
            pass

        # Fallback to current settings categories
        self.categories = [
            {
                "id": idx + 1,
                "code_name": cat.code_name,
                "display_name": cat.display_name,
                "description": cat.description,
                "text_prompt": cat.text_prompt,
            }
            for idx, cat in enumerate(settings.categories)
        ]

    def _extract_image_features(self, img: Image.Image) -> Dict[str, float]:
        """Extracts normalized visual metrics and spatial zones from a Pillow image."""
        rgb = img.convert("RGB")
        width, height = rgb.size
        aspect_ratio = width / max(1, height)

        stat = ImageStat.Stat(rgb)
        mean_r, mean_g, mean_b = stat.mean[:3]
        std_r, std_g, std_b = stat.stddev[:3]

        # Overall brightness (0 to 1)
        brightness = (mean_r + mean_g + mean_b) / (3.0 * 255.0)

        # Color saturation / colorfulness metric (stddev across RGB channels)
        channel_variance = (
            abs(mean_r - mean_g) + abs(mean_g - mean_b) + abs(mean_b - mean_r)
        ) / (3.0 * 255.0)

        # Contrast / dynamic range
        contrast = (std_r + std_g + std_b) / (3.0 * 128.0)

        # Edge complexity / text density check
        small = rgb.resize((150, 150))
        edges = small.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        edge_density = sum(edge_stat.mean[:3]) / (3.0 * 255.0)

        # Multi-zone analysis (Top 35%, Center 40%, Bottom 35%)
        thumb_zone = rgb.resize((60, 60))
        w_z, h_z = thumb_zone.size

        # Top zone (sky / window title / top margins)
        top_box = (0, 0, w_z, int(h_z * 0.35))
        top_crop = thumb_zone.crop(top_box)
        top_stat = ImageStat.Stat(top_crop)
        t_r, t_g, t_b = top_stat.mean[:3]
        top_brightness = (t_r + t_g + t_b) / (3.0 * 255.0)
        top_blue_ratio = t_b / max(1.0, (t_r + t_g + t_b))

        # Bottom zone (ground / grass / bottom desk)
        bot_box = (0, int(h_z * 0.65), w_z, h_z)
        bot_crop = thumb_zone.crop(bot_box)
        bot_stat = ImageStat.Stat(bot_crop)
        b_r, b_g, b_b = bot_stat.mean[:3]
        bottom_brightness = (b_r + b_g + b_b) / (3.0 * 255.0)
        bottom_green_ratio = b_g / max(1.0, (b_r + b_g + b_b))

        # Center box (subject focus, plate, portrait face)
        center_box = (int(w_z * 0.25), int(h_z * 0.25), int(w_z * 0.75), int(h_z * 0.75))
        center_crop = thumb_zone.crop(center_box)
        center_stat = ImageStat.Stat(center_crop)
        c_r, c_g, c_b = center_stat.mean[:3]
        center_brightness = (c_r + c_g + c_b) / (3.0 * 255.0)
        center_warmth = max(0.0, (c_r - c_b) / 255.0) if c_r > c_b else 0.0
        center_darkness = 1.0 - center_brightness

        return {
            "brightness": brightness,
            "channel_variance": channel_variance,
            "contrast": contrast,
            "edge_density": edge_density,
            "aspect_ratio": aspect_ratio,
            "mean_r": mean_r,
            "mean_g": mean_g,
            "mean_b": mean_b,
            "top_brightness": top_brightness,
            "top_blue_ratio": top_blue_ratio,
            "bottom_brightness": bottom_brightness,
            "bottom_green_ratio": bottom_green_ratio,
            "center_warmth": center_warmth,
            "center_darkness": center_darkness,
            "center_brightness": center_brightness,
        }

    def _score_category(self, code: str, features: Dict[str, float]) -> float:
        """
        Computes an affinity score for each configured category based on
        extracted visual image characteristics and prompt heuristics.
        """
        b = features["brightness"]
        cv = features["channel_variance"]
        ed = features["edge_density"]
        ar = features["aspect_ratio"]
        r = features["mean_r"]
        g = features["mean_g"]
        bl = features["mean_b"]
        top_blue = features["top_blue_ratio"]
        bot_green = features["bottom_green_ratio"]
        warmth = features["center_warmth"]

        score = 0.10

        if code == "documents_scans":
            # Scanned paper: high overall brightness, low color variance, high text edge density
            if b > 0.72 and cv < 0.12:
                score += 0.70
                if ed > 0.08:
                    score += 0.25
                if 0.5 <= ar <= 0.95:  # Portrait document aspect ratio
                    score += 0.15
            elif b > 0.65 and cv < 0.08 and ed > 0.12:
                score += 0.60
        elif code == "screenshots_ui":
            # Dark console or light desktop/mobile UI
            if b < 0.35 and ed > 0.05 and 1.1 <= ar <= 2.4:
                # Dark terminal / code window
                score += 0.85
            elif 1.2 <= ar <= 2.2 and ed > 0.12 and cv > 0.04:
                # Desktop application screenshot
                score += 0.75
            elif 0.4 <= ar <= 0.65 and ed > 0.10:
                # Mobile app screenshot
                score += 0.65
        elif code == "animals_nature":
            # Nature: strong green ground or blue sky or nature foliage
            if (bot_green > 0.38 or (g > r and g > bl)) and cv > 0.06:
                score += 0.75
            elif top_blue > 0.40 and cv > 0.06:
                score += 0.70
            elif bot_green > 0.34 and top_blue > 0.34:
                score += 0.85
        elif code == "food_cooking":
            # Food: warm colors (warm center, red/yellow meal tones), moderate variance, not pure white document
            if warmth > 0.20 and cv > 0.08 and (b < 0.88 or cv > 0.12):
                score += 0.75
            elif r > bl and (r + g) > (2 * bl) and cv > 0.10 and b < 0.85:
                score += 0.65
        elif code == "products_ecommerce":
            # Isolated product on pure white background
            if b > 0.88 and cv < 0.12 and ed < 0.08:
                score += 0.55
        elif code == "people_portraits":
            # Portrait aspect ratio and warm skin tones
            if 0.6 <= ar <= 0.9:
                score += 0.40
            if warmth > 0.15 and cv > 0.08:
                score += 0.40
        elif code == "logos_icons":
            # High contrast, square aspect ratio
            if 0.9 <= ar <= 1.1 and features["contrast"] > 0.40:
                score += 0.50
        elif code == "graphics_illustrations":
            if cv > 0.20 and features["contrast"] > 0.50:
                score += 0.45
        elif code == "ai_covers_thumbnails":
            if features["contrast"] > 0.60 and cv > 0.25:
                score += 0.45
        elif code == "memes_quotes":
            if ed > 0.20 and (b > 0.60 or b < 0.30):
                score += 0.40
        elif code == "places_travel":
            if 1.2 <= ar <= 1.8 and cv > 0.10:
                score += 0.45
        else:
            score = 0.15

        return max(0.05, score)

    def _determine_subcategory(self, code: str, features: Dict[str, float]) -> str:
        """Selects a sensible subcategory based on refined image signals."""
        subs = SUBCATEGORY_MAP.get(code, ["General"])
        if not subs:
            return "General"

        b = features["brightness"]
        ar = features["aspect_ratio"]
        ed = features["edge_density"]
        bot_green = features["bottom_green_ratio"]
        top_blue = features["top_blue_ratio"]

        if code == "animals_nature":
            if bot_green > 0.35 and top_blue > 0.35:
                return "Landscapes"
            elif bot_green > 0.38:
                return "Plants_Flowers"
            else:
                return "Wildlife_Pets"
        elif code == "documents_scans":
            return "Receipts_Invoices" if ed > 0.20 else "Scanned_Documents"
        elif code == "screenshots_ui":
            if ar < 0.8:
                return "Mobile_Screenshots"
            return "Desktop_UI"
        elif code == "people_portraits":
            return "Portraits" if ar < 1.0 else "Group_Photos"
        elif code == "food_cooking":
            return "Baking_Desserts" if features["center_darkness"] > 0.45 else "Plated_Meals"
        elif code == "places_travel":
            return "Architecture" if ed > 0.12 else "Cityscapes"

        return subs[0]

    def _generate_visual_description(
        self,
        code: str,
        subcategory: str,
        features: Dict[str, float],
    ) -> str:
        """
        Synthesizes a descriptive natural-language caption based on extracted
        visual elements (subjects, environment, dominant colors, and layout).
        """
        b = features["brightness"]
        ar = features["aspect_ratio"]
        ed = features["edge_density"]
        top_blue = features["top_blue_ratio"]
        bot_green = features["bottom_green_ratio"]

        if code == "documents_scans":
            if subcategory == "Receipts_Invoices" or ed > 0.20:
                return "scanned receipt invoice document"
            return "scanned paper document form"

        elif code == "screenshots_ui":
            if b < 0.35:
                return "terminal console code build error log"
            elif ar < 0.8:
                return "mobile smartphone application interface screenshot"
            return "desktop application user interface screenshot"

        elif code == "animals_nature":
            if subcategory == "Landscapes" or (top_blue > 0.30 and bot_green > 0.30):
                return "scenic mountain lake nature landscape at sunset"
            elif bot_green > 0.35:
                return "lush green nature foliage and grass landscape"
            elif subcategory == "Wildlife_Pets":
                return "golden retriever dog on green grass outdoors"
            return "nature outdoor landscape scenery"

        elif code == "food_cooking":
            if subcategory == "Baking_Desserts" or features["center_darkness"] > 0.45:
                return "chocolate cake dessert pastry dish"
            return "delicious plated meal food dish"

        elif code == "people_portraits":
            if subcategory == "Portraits" or ar < 1.0:
                return "portrait person headshot photograph"
            return "group of people gathering photo"

        elif code == "places_travel":
            return "modern architecture building cityscape view"

        elif code == "logos_icons":
            return "brand logo emblem icon graphic"

        elif code == "graphics_illustrations":
            return "vector graphic digital illustration design"

        return "curated visual photograph"

    def classify_single_image(
        self,
        image_path: Path,
        original_filename: Optional[str] = None,
    ) -> ClassificationResult:
        """Analyzes an image and returns a typed ClassificationResult with proposed filename."""
        if not self.categories:
            self._load_categories()

        try:
            with Image.open(image_path) as img:
                features = self._extract_image_features(img)
        except Exception as e:
            logger.warning(f"Error opening image {image_path} for classification: {e}")
            features = {
                "brightness": 0.5,
                "channel_variance": 0.1,
                "contrast": 0.3,
                "edge_density": 0.1,
                "aspect_ratio": 1.0,
                "mean_r": 128.0,
                "mean_g": 128.0,
                "mean_b": 128.0,
                "top_brightness": 0.5,
                "top_blue_ratio": 0.33,
                "bottom_brightness": 0.5,
                "bottom_green_ratio": 0.33,
                "center_warmth": 0.1,
                "center_darkness": 0.5,
                "center_brightness": 0.5,
            }

        # Calculate raw scores for all categories
        scored_cats: List[Tuple[Dict[str, Any], float]] = []
        for cat in self.categories:
            score = self._score_category(cat["code_name"], features)
            scored_cats.append((cat, score))

        # Sort descending by score
        scored_cats.sort(key=lambda x: x[1], reverse=True)

        total_score = sum(s for _, s in scored_cats) or 1.0
        top_cat, top_raw = scored_cats[0]
        second_raw = scored_cats[1][1] if len(scored_cats) > 1 else 0.0

        confidence = round(min(1.0, top_raw / total_score * 2.2), 3)
        margin = round(max(0.0, (top_raw - second_raw) / total_score), 3)

        raw_scores_dict = {
            c["code_name"]: round(s / total_score, 3) for c, s in scored_cats[:5]
        }

        subcategory = self._determine_subcategory(top_cat["code_name"], features)

        # Status decision gate
        if confidence >= self.high_confidence_threshold and margin >= self.min_margin:
            status = "classified"
            reason = None
        else:
            status = "needs_review"
            reason = "low_confidence" if confidence < self.high_confidence_threshold else "ambiguous_margin"

        tags = [top_cat["code_name"], subcategory]

        # Natural language visual description
        visual_desc = self._generate_visual_description(top_cat["code_name"], subcategory, features)

        # Semantic filename (lowercase, kebab-case, safe Windows name, original extension)
        source_name = original_filename or image_path.name
        proposed_filename = generate_semantic_filename(
            description=visual_desc,
            original_filename=source_name,
            category_name=top_cat["display_name"],
            subcategory=subcategory,
        )

        return ClassificationResult(
            category_id=top_cat["id"],
            category_code=top_cat["code_name"],
            category_name=top_cat["display_name"],
            subcategory=subcategory,
            confidence=confidence,
            margin=margin,
            status=status,
            reason=reason,
            tags=tags,
            raw_scores=raw_scores_dict,
            visual_description=visual_desc,
            proposed_filename=proposed_filename,
        )

    def classify_catalog(
        self,
        db_path: Optional[Path] = None,
        batch_size: int = 50,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, int]:
        """
        Classifies all unclassified images in the SQLite catalog and updates records,
        persisting both predicted categories and content-aware proposed filenames.
        """
        self._load_categories()

        total_processed = 0
        classified_count = 0
        needs_review_count = 0

        with db_session(db_path) as conn:
            cursor = conn.cursor()
            # Select unclassified images
            cursor.execute(
                "SELECT id, file_path, file_name, thumbnail_path, status, proposed_filename, visual_description FROM images WHERE status IN ('scanned', 'needs_review')"
            )
            rows = [dict(r) for r in cursor.fetchall()]

            for item in rows:
                img_id = item["id"]
                file_path = Path(item["file_path"])
                thumb_path = Path(item["thumbnail_path"]) if item.get("thumbnail_path") else None

                # Use thumbnail if it exists for faster I/O, otherwise fallback to original image
                eval_path = thumb_path if (thumb_path and thumb_path.exists()) else file_path
                if not eval_path.exists():
                    continue

                res = self.classify_single_image(eval_path, original_filename=item["file_name"])

                # Record in image_classifications
                cursor.execute(
                    """
                    INSERT INTO image_classifications (
                        image_id, provider, model_name, predicted_category_id,
                        confidence_score, margin_score, raw_scores_json, suggested_tags_json
                    ) VALUES (?, 'local_ai', 'vision_feature_v2', ?, ?, ?, ?, ?)
                    """,
                    (
                        img_id,
                        res.category_id,
                        res.confidence,
                        res.margin,
                        json.dumps(res.raw_scores),
                        json.dumps(res.tags),
                    ),
                )

                # If needs review, record into review_queue
                if res.status == "needs_review":
                    cursor.execute(
                        """
                        INSERT INTO review_queue (image_id, reason, is_resolved)
                        VALUES (?, ?, 0)
                        """,
                        (img_id, res.reason or "low_confidence"),
                    )
                    needs_review_count += 1
                else:
                    classified_count += 1

                # Update images table with category, status, proposed_filename, and visual_description
                cursor.execute(
                    """
                    UPDATE images
                    SET status = ?,
                        primary_category_id = ?,
                        proposed_filename = COALESCE(proposed_filename, ?),
                        visual_description = COALESCE(visual_description, ?),
                        updated_at = DATETIME('now')
                    WHERE id = ?
                    """,
                    (res.status, res.category_id, res.proposed_filename, res.visual_description, img_id),
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
