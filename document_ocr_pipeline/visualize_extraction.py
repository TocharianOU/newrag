#!/usr/bin/env python3
"""
Visualize OCR extraction results by drawing bounding boxes on the image
"""
import json
import cv2
import numpy as np
from pathlib import Path
import argparse


def visualize_extraction(image_path: str, json_path: str, output_path: str):
    """
    Visualize extraction results by drawing boxes on the image
    
    Args:
        image_path: Path to original image
        json_path: Path to extraction JSON results
        output_path: Path to save visualization
    """
    # Read image
    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Failed to read image: {image_path}")
        return
    
    # Read JSON results
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Create a copy for drawing
    vis_image = image.copy()
    
    # Draw text blocks
    text_blocks = data.get('text_blocks', [])
    print(f"Drawing {len(text_blocks)} text blocks...")
    
    for idx, block in enumerate(text_blocks):
        bbox = block['bbox']
        text = block['text']
        confidence = block['confidence']
        
        # Convert to integer coordinates
        x1, y1, x2, y2 = map(int, bbox)
        
        # Color based on confidence (green = high, yellow = medium, red = low)
        if confidence > 0.8:
            color = (0, 255, 0)  # Green
        elif confidence > 0.5:
            color = (0, 255, 255)  # Yellow
        else:
            color = (0, 0, 255)  # Red
        
        # Draw rectangle
        cv2.rectangle(vis_image, (x1, y1), (x2, y2), color, 2)
        
        # Draw text label with background
        label = f"{text[:20]}..." if len(text) > 20 else text
        font_scale = 0.4
        thickness = 1
        (label_width, label_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        
        # Draw background rectangle for text
        cv2.rectangle(
            vis_image,
            (x1, y1 - label_height - baseline - 5),
            (x1 + label_width, y1),
            color,
            -1
        )
        
        # Draw text
        cv2.putText(
            vis_image,
            label,
            (x1, y1 - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness
        )
    
    # Draw layout regions in blue
    layout_regions = data.get('layout_regions', [])
    if layout_regions:
        print(f"Drawing {len(layout_regions)} layout regions...")
        for region in layout_regions:
            bbox = region['bbox']
            x1, y1, x2, y2 = map(int, bbox)
            
            # Skip invalid regions
            if x2 - x1 < 5 or y2 - y1 < 5:
                continue
            
            # Draw blue rectangle for layout regions
            cv2.rectangle(vis_image, (x1, y1), (x2, y2), (255, 0, 0), 3)
    
    # Add legend
    legend_y = 30
    cv2.putText(vis_image, "Legend:", (10, legend_y), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.putText(vis_image, "Green: High confidence (>0.8)", (10, legend_y + 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    cv2.putText(vis_image, "Yellow: Medium confidence (0.5-0.8)", (10, legend_y + 50), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
    cv2.putText(vis_image, "Red: Low confidence (<0.5)", (10, legend_y + 75), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    
    # Save result
    cv2.imwrite(output_path, vis_image)
    print(f"\n✓ Visualization saved to: {output_path}")
    
    # Print statistics
    print(f"\nStatistics:")
    print(f"  - Total text blocks: {len(text_blocks)}")
    print(f"  - Layout regions: {len(layout_regions) if layout_regions else 0}")
    print(f"  - Average confidence: {data.get('average_confidence', 0)*100:.2f}%")
    
    high_conf = sum(1 for b in text_blocks if b['confidence'] > 0.8)
    med_conf = sum(1 for b in text_blocks if 0.5 <= b['confidence'] <= 0.8)
    low_conf = sum(1 for b in text_blocks if b['confidence'] < 0.5)
    
    print(f"  - High confidence blocks: {high_conf}")
    print(f"  - Medium confidence blocks: {med_conf}")
    print(f"  - Low confidence blocks: {low_conf}")


def main():
    parser = argparse.ArgumentParser(description="Visualize OCR extraction results")
    parser.add_argument("image", help="Path to original image")
    parser.add_argument("json", help="Path to extraction JSON file")
    parser.add_argument("-o", "--output", help="Output image path (default: input_visualized.jpg)")
    
    args = parser.parse_args()
    
    image_path = Path(args.image)
    json_path = Path(args.json)
    
    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        return 1
    
    if not json_path.exists():
        print(f"Error: JSON not found: {json_path}")
        return 1
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = image_path.with_stem(image_path.stem + "_visualized")
    
    visualize_extraction(str(image_path), str(json_path), str(output_path))
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

