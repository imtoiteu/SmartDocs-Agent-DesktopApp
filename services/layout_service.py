import os
import logging
import cv2
import numpy as np

# Try to import layoutparser
try:
    import layoutparser as lp
    LP_AVAILABLE = True
except ImportError:
    LP_AVAILABLE = False
    lp = None

# Import existing geometric logic for fallback/integration
try:
    from .geometry_service import reconstruct_layout as geometric_reconstruct
except ImportError:
    # If not found, define a pass-through fallback
    def geometric_reconstruct(results, img_width, img_height):
        return results

logger = logging.getLogger(__name__)

def _get_box_center(item):
    box = item.get("box")
    if not box or len(box) != 4:
        return 0, 0
    xs = [pt[0] for pt in box]
    ys = [pt[1] for pt in box]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

class LayoutParserService:
    def __init__(self):
        self.model = None
        self._initialized = False
        self._enabled = LP_AVAILABLE
        self._region_cache = {}
        # Phase 1: Load a lightweight pretrained model from the official LayoutParser project.
        # Verified model: PubLayNet PPYOLOv2 (best compatibility with Paddle backend)
        self.model_path = "lp://PubLayNet/ppyolov2_r50vd_dcn_365e/config"
        
    def initialize(self):
        """Initializes the LayoutParser model with a graceful fallback."""
        if not self._enabled:
            return False
        if self._initialized:
            return True
            
        try:
            # AutoLayoutModel handles backend detection automatically
            self.model = lp.AutoLayoutModel(
                self.model_path,
                extra_config={"threshold": 0.5}
            )
            
            # Fallback for AutoLayoutModel returning None
            if self.model is None:
                from layoutparser.models.paddledetection import PaddleDetectionLayoutModel
                self.model = PaddleDetectionLayoutModel(self.model_path)

            if self.model:
                self._initialized = True
                logger.info(f"LayoutParser model '{self.model_path}' initialized successfully.")
                return True
            else:
                raise ValueError("Model initialization returned None")
        except Exception as e:
            logger.warning(f"LayoutParser initialization failed: {e}. Falling back to geometric analysis.")
            self._enabled = False
            return False

    def detect_regions(self, image):
        """
        Detects layout regions such as text blocks, titles, lists, tables, and figures.
        Returns a list of regions: {"type": str, "box": [x1, y1, x2, y2], "score": float}
        """
        if not self.initialize():
            return []
            
        # Cache check
        if isinstance(image, str) and image in self._region_cache:
            return self._region_cache[image]

        try:
            # Handle path or numpy array
            img_to_process = image
            if isinstance(image, str):
                if not os.path.exists(image):
                    return []
                img_to_process = cv2.imread(image)
                if img_to_process is None:
                    return []
                img_to_process = cv2.cvtColor(img_to_process, cv2.COLOR_BGR2RGB)
            
            # Perform inference
            layout = self.model.detect(img_to_process)
            
            regions = []
            for block in layout:
                regions.append({
                    "type": block.type.lower() if block.type else "text",
                    "box": [float(block.block.x_1), float(block.block.y_1), 
                            float(block.block.x_2), float(block.block.y_2)],
                    "score": float(getattr(block, 'score', 1.0))
                })
            
            if isinstance(image, str):
                self._region_cache[image] = regions

            return regions
        except Exception as e:
            logger.error(f"LayoutParser detection error: {e}")
            return []

    def ai_guided_reconstruct(self, results, img_width, img_height, image):
        """
        Uses detected layout regions to guide the grouping and ordering of OCR text.
        """
        regions = self.detect_regions(image)
        if not regions:
            return None # Fallback to geometric

        # 1. Map OCR boxes to regions
        region_buckets = [[] for _ in regions]
        background_bucket = []
        
        for item in results:
            cx, cy = _get_box_center(item)
            
            best_region_idx = -1
            for i, r in enumerate(regions):
                x1, y1, x2, y2 = r["box"]
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    best_region_idx = i
                    break
            
            if best_region_idx >= 0:
                region_buckets[best_region_idx].append(item)
            else:
                background_bucket.append(item)

        # 2. Sort regions by reading order: Column-first
        # (Left to Right, then Top to Bottom within columns)
        sorted_indices = sorted(
            range(len(regions)),
            key=lambda i: (regions[i]["box"][0] // (img_width * 0.2 if img_width > 0 else 100), regions[i]["box"][1])
        )
        
        ordered_results = []
        for i in sorted_indices:
            bucket = region_buckets[i]
            if not bucket: continue
            # Sort within region using the restored stable geometric engine
            ordered_results.extend(geometric_reconstruct(bucket, img_width, img_height))
            
        if background_bucket:
            ordered_results.extend(geometric_reconstruct(background_bucket, img_width, img_height))
            
        return ordered_results

# Singleton instance for the application
_lp_service = LayoutParserService()

def detect_layout_regions(image):
    """
    Public API for region detection.
    Returns: [{'type': 'text'|'title'|'list'|'table'|'figure', 'box': [x1,y1,x2,y2], 'score': 0.9}]
    """
    return _lp_service.detect_regions(image)

def reconstruct_layout(results, img_width, img_height, image=None):
    """
    Reconstruct natural reading order from raw OCR results.
    Phase 2: Uses LayoutParser to guide region-based sorting.
    """
    if image and _lp_service._enabled:
        try:
            ai_results = _lp_service.ai_guided_reconstruct(results, img_width, img_height, image)
            if ai_results:
                return ai_results
        except Exception as e:
            logger.error(f"AI-guided reconstruction failed: {e}. Falling back to geometric.")
            
    # Fallback to standard geometric logic
    return geometric_reconstruct(results, img_width, img_height)
