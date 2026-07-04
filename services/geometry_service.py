import statistics
import copy
from typing import List, Dict, Any

def _get_bbox(item: Dict[str, Any]) -> tuple:
    box = item.get("box")
    if not box or len(box) != 4:
        return 0, 0, 0, 0
    xs = [pt[0] for pt in box]
    ys = [pt[1] for pt in box]
    return min(xs), min(ys), max(xs), max(ys)

def _merge_intervals(intervals: List[tuple], max_gap: float) -> List[tuple]:
    """Merge [start, end] intervals that overlap or have a gap <= max_gap."""
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for current in intervals[1:]:
        prev = merged[-1]
        if current[0] <= prev[1] + max_gap:
            merged[-1] = (prev[0], max(prev[1], current[1]))
        else:
            merged.append(current)
    return merged

def _merge_blocks(b1: Dict[str, Any], b2: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(b1)
    merged["text"] = b1.get("text", "") + " " + b2.get("text", "")
    
    xmin1, ymin1, xmax1, ymax1 = _get_bbox(b1)
    xmin2, ymin2, xmax2, ymax2 = _get_bbox(b2)
    
    xmin = min(xmin1, xmin2)
    ymin = min(ymin1, ymin2)
    xmax = max(xmax1, xmax2)
    ymax = max(ymax1, ymax2)
    
    merged["box"] = [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]]
    
    c1 = b1.get("confidence")
    c2 = b2.get("confidence")
    if c1 is not None and c2 is not None:
        merged["confidence"] = round((c1 + c2) / 2, 4)
    else:
        merged["confidence"] = c1 if c1 is not None else c2
        
    return merged

def _sort_blocks_in_column(blocks: List[Dict[str, Any]], median_h: float) -> List[Dict[str, Any]]:
    if not blocks:
        return []
    blocks.sort(key=lambda b: b["cy"])
    lines = []
    current_line = [blocks[0]]
    for b in blocks[1:]:
        avg_cy = sum(cb["cy"] for cb in current_line) / len(current_line)
        if abs(b["cy"] - avg_cy) < median_h * 0.5:
            current_line.append(b)
        else:
            lines.append(current_line)
            current_line = [b]
    lines.append(current_line)
    
    for line in lines:
        line.sort(key=lambda b: b["xmin"])
        
    return [b for line in lines for b in line]

def _needs_reconstruction(blocks: List[Dict[str, Any]], band_groups: List[List[Dict[str, Any]]], median_h: float) -> bool:
    for band_blocks in band_groups:
        if not band_blocks: continue
        x_intervals = [(b["xmin"], b["xmax"]) for b in band_blocks]
        columns = _merge_intervals(x_intervals, max_gap=median_h * 1.5)
        if len(columns) > 1:
            return True
            
    for i in range(1, len(blocks)):
        if blocks[i]["ymin"] < blocks[i-1]["ymin"] - median_h * 1.5:
            return True
            
    return False

def _vertical_merge_pass2(blocks: List[Dict[str, Any]], median_h: float) -> List[Dict[str, Any]]:
    """
    Implements a SECOND PASS vertical merge step to improve paragraph continuity.
    Only merges blocks that are vertically nearby and horizontally aligned.
    """
    if not blocks:
        return []
        
    merged_results = []
    curr = copy.deepcopy(blocks[0])
    
    for next_b in blocks[1:]:
        # Get bboxes
        x1_a, y1_a, x2_a, y2_a = _get_bbox(curr)
        x1_b, y1_b, x2_b, y2_b = _get_bbox(next_b)
        
        w_a = x2_a - x1_a
        w_b = x2_b - x1_b
        h_a = y2_a - y1_a
        h_b = y2_b - y1_b
        
        # 1. Vertical proximity
        v_gap = y1_b - y2_a
        cond1 = 0 <= v_gap < median_h * 1.5
        
        # 2. Horizontal alignment (left edge)
        tolerance_x = min(w_a, w_b) * 0.2
        cond2 = abs(x1_a - x1_b) < tolerance_x
        
        # 3. Same column (horizontal overlap ratio > 0.5)
        overlap = min(x2_a, x2_b) - max(x1_a, x1_b)
        min_w = min(w_a, w_b)
        cond3 = (overlap / min_w > 0.5) if min_w > 0 else False
        
        # 4. Similar font size
        cond4 = abs(h_a - h_b) / h_a < 0.5 if h_a > 0 else False
        
        if cond1 and cond2 and cond3 and cond4:
            # Merge
            curr = _merge_blocks(curr, next_b)
        else:
            merged_results.append(curr)
            curr = copy.deepcopy(next_b)
            
    merged_results.append(curr)
    return merged_results

def reconstruct_layout(results: List[Dict[str, Any]], img_width: int, img_height: int) -> List[Dict[str, Any]]:
    """
    Reconstruct natural reading order using a 5-step geometric pipeline plus a second-pass vertical merge.
    1. Line Grouping (Vertical overlap/center)
    2. Line Reconstruction (Horizontal sort/merge)
    3. Header/Title Detection
    4. Column Clustering
    5. Final Reading Order & Paragraph Merging (Pass 1)
    6. Second-Pass Vertical Merging (Continuity)
    """
    if not results:
        return []
    
    # Enrich blocks with bbox data and filter noise
    blocks = []
    heights = []
    for item in results:
        xmin, ymin, xmax, ymax = _get_bbox(item)
        if xmax <= xmin or ymax <= ymin or (xmax - xmin) < 2 or (ymax - ymin) < 2:
            continue
        blocks.append({
            "item": copy.deepcopy(item),
            "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
            "cx": (xmin + xmax) / 2, "cy": (ymin + ymax) / 2,
            "h": ymax - ymin, "w": xmax - xmin
        })
        heights.append(ymax - ymin)
    
    if not blocks:
        return []
        
    median_h = statistics.median(heights) if heights else 10.0
    
    # --- STEP 1 & 2: LINE GROUPING & RECONSTRUCTION ---
    # Group boxes into lines using similar vertical centers
    blocks.sort(key=lambda b: b["cy"])
    lines_raw = []
    if blocks:
        current_line = [blocks[0]]
        for b in blocks[1:]:
            avg_cy = sum(cb["cy"] for cb in current_line) / len(current_line)
            # Threshold for line grouping: 40% of median height
            if abs(b["cy"] - avg_cy) < median_h * 0.4:
                current_line.append(b)
            else:
                lines_raw.append(current_line)
                current_line = [b]
        lines_raw.append(current_line)
    
    # For each line, sort boxes left->right and merge into fragments
    # We must NOT merge across large horizontal gaps (columns)
    lines = []
    for line_blocks in lines_raw:
        line_blocks.sort(key=lambda b: b["xmin"])
        
        # Split line_blocks into fragments if horizontal gap is too large
        fragments = []
        if line_blocks:
            curr_frag = [line_blocks[0]]
            for b in line_blocks[1:]:
                prev = curr_frag[-1]
                h_gap = b["xmin"] - prev["xmax"]
                if h_gap < median_h * 3.0: # Threshold for intra-line merging
                    curr_frag.append(b)
                else:
                    fragments.append(curr_frag)
                    curr_frag = [b]
            fragments.append(curr_frag)
            
        for frag in fragments:
            line_item = frag[0]["item"]
            for b in frag[1:]:
                line_item = _merge_blocks(line_item, b["item"])
            
            # Enrich merged line fragment with geometry
            xmin, ymin, xmax, ymax = _get_bbox(line_item)
            lines.append({
                "item": line_item,
                "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
                "cx": (xmin + xmax) / 2, "cy": (ymin + ymax) / 2,
                "h": ymax - ymin, "w": xmax - xmin
            })

    # --- STEP 5: SPECIAL CASES (HEADER/TITLE) ---
    # Detect titles/headers BEFORE column clustering
    titles = []
    body_lines = []
    for l in lines:
        # Title: Very wide OR centered + tall + at top
        is_wide = l["w"] > img_width * 0.7
        is_centered = abs(l["cx"] - img_width/2) < img_width * 0.12
        is_tall = l["h"] > median_h * 1.3
        is_at_top = l["ymin"] < img_height * 0.25
        
        if is_wide or (is_centered and is_tall and is_at_top):
            titles.append(l)
        else:
            body_lines.append(l)
            
    # Sort titles by Y
    titles.sort(key=lambda x: x["ymin"])

    # --- STEP 3: COLUMN DETECTION ---
    # Cluster remaining lines into columns based on X positions
    columns = []
    if body_lines:
        body_lines.sort(key=lambda l: l["cx"])
        for l in body_lines:
            best_col = None
            for col in columns:
                col_cx = sum(cl["cx"] for cl in col) / len(col)
                # Max gap for column grouping: 15% width or 4x median height
                if abs(l["cx"] - col_cx) < max(img_width * 0.15, median_h * 4):
                    best_col = col
                    break
            if best_col is not None:
                best_col.append(l)
            else:
                columns.append([l])
                
    # Sort columns by average X (Left -> Right)
    columns.sort(key=lambda col: sum(cl["cx"] for cl in col) / len(col))
    
    # --- STEP 4: READING ORDER & STEP 5: PARAGRAPH MERGING (PASS 1) ---
    # Header -> Column 1 (top-to-bottom) -> Column 2 (top-to-bottom)
    # Inside each group, merge lines into paragraphs.
    
    pass1_result = []
    
    # 1. Process Titles/Headers
    if titles:
        titles.sort(key=lambda l: l["ymin"])
        curr = titles[0]["item"]
        for next_t in titles[1:]:
            xmin1, ymin1, xmax1, ymax1 = _get_bbox(curr)
            xmin2, ymin2, xmax2, ymax2 = _get_bbox(next_t["item"])
            v_gap = ymin2 - ymax1
            if 0 <= v_gap < median_h * 1.0: # Close titles/headers merge
                curr = _merge_blocks(curr, next_t["item"])
            else:
                pass1_result.append(curr)
                curr = next_t["item"]
        pass1_result.append(curr)
        
    # 2. Process each Column
    for col in columns:
        col.sort(key=lambda l: l["ymin"])
        if not col: continue
        
        curr = col[0]["item"]
        for next_l in col[1:]:
            xmin1, ymin1, xmax1, ymax1 = _get_bbox(curr)
            xmin2, ymin2, xmax2, ymax2 = _get_bbox(next_l["item"])
            
            v_gap = ymin2 - ymax1
            left_diff = abs(xmin2 - xmin1)
            
            # Paragraph merge thresholds (Pass 1):
            if 0 <= v_gap < median_h * 1.4 and left_diff < median_h * 2.0:
                curr = _merge_blocks(curr, next_l["item"])
            else:
                pass1_result.append(curr)
                curr = next_l["item"]
        pass1_result.append(curr)
            
    # --- STEP 6: SECOND-PASS VERTICAL MERGE (CONTINUITY) ---
    enable_merge_pass2 = True
    if enable_merge_pass2:
        try:
            pass2_result = _vertical_merge_pass2(pass1_result, median_h)
            
            # Safety Fallback
            # 1. Check if block count reduced too aggressively (> 70% reduction in one pass is risky)
            if len(pass1_result) > 5 and len(pass2_result) < len(pass1_result) * 0.3:
                return pass1_result
                
            # 2. Check for abnormal boxes (e.g. height > 80% of image)
            for b in pass2_result:
                _, y1, _, y2 = _get_bbox(b)
                if (y2 - y1) > img_height * 0.8:
                    return pass1_result
                    
            final_res = pass2_result
        except Exception:
            final_res = pass1_result
    else:
        final_res = pass1_result

    # --- FINAL PASS: STRICT COLUMN-BASED ORDERING ---
    # Apply column-first sorting to the final merged results to ensure
    # that Text Results panel and exports follow the natural reading order.
    if not final_res:
        return []

    # Group final blocks into headers and columns
    headers = []
    body_blocks = []
    
    for b in final_res:
        x1, y1, x2, y2 = _get_bbox(b)
        is_wide = (x2 - x1) > img_width * 0.6
        is_centered = abs((x1 + x2)/2 - img_width/2) < img_width * 0.15
        is_top = y1 < img_height * 0.3
        
        if is_top and (is_wide or is_centered):
            headers.append(b)
        else:
            body_blocks.append(b)
            
    headers.sort(key=lambda b: _get_bbox(b)[1]) # Sort headers by Y
    
    # Cluster body blocks into columns
    final_columns = []
    temp_body = []
    for b in body_blocks:
        x1, y1, x2, y2 = _get_bbox(b)
        temp_body.append({
            "item": b,
            "cx": (x1 + x2) / 2,
            "cy": (y1 + y2) / 2,
            "ymin": y1
        })
    
    temp_body.sort(key=lambda x: x["cx"])
    
    for b in temp_body:
        best_col = None
        for col in final_columns:
            col_cx = sum(cl["cx"] for cl in col) / len(col)
            if abs(b["cx"] - col_cx) < (img_width * 0.15):
                best_col = col
                break
        if best_col is not None:
            best_col.append(b)
        else:
            final_columns.append([b])
            
    # Sort columns by average X
    final_columns.sort(key=lambda col: sum(cl["cx"] for cl in col) / len(col))
    
    final_ordered = headers
    for col in final_columns:
        col.sort(key=lambda l: l["ymin"])
        for l in col:
            final_ordered.append(l["item"])
            
    return final_ordered
