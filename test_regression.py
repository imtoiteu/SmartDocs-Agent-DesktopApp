from services import layout_service

results = [
    {"text": "Hello", "box": [[10, 10], [50, 10], [50, 20], [10, 20]]},
    {"text": "World", "box": [[60, 9], [100, 9], [100, 19], [60, 19]]},
]

blocks = []
for item in results:
    xmin, ymin, xmax, ymax = layout_service._get_bbox(item)
    blocks.append({
        "item": item,
        "xmin": xmin, "ymin": ymin, "cx": (xmin+xmax)/2, "cy": (ymin+ymax)/2
    })

def sort_blocks(blocks, median_h):
    if not blocks: return []
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

ordered = sort_blocks(blocks, 10)
for i, item in enumerate(ordered):
    print(f"[{i}] {item['item']['text']}")

