import cv2
import os
import csv
import json
import argparse
from data_ingestion import VideoIngestor, MetadataParser
from detection import PersonDetector
from transformation import CoordinateTransformer
from heatmap import HeatmapGenerator

def run_pipeline(
    video_path: str,
    metadata_path: str,
    output_path: str,
    model_type: str = "sdnet",
    model_path: str | None = None,
    device: str | None = None,
    yolo_confidence: float = 0.35,
):
    print(f"Starting heatmap pipeline for {video_path} using model '{model_type}'")
    
    # 1. Setup Ingestion
    ingestor = VideoIngestor(video_path)
    props = ingestor.get_video_properties()
    print(f"Video Properties: {props}")
    
    # Parse the metadata JSON
    parser = MetadataParser(metadata_path)
    meta = parser.load_metadata()

    # Support both static and per-frame metadata
    # Static: { "altitude": 50, "fov_h": 60, ... }
    # Per-frame: { "static": { "fov_h": 60, "fov_v": 45 }, "frames": [ { "latitude": ..., "longitude": ..., "altitude": ..., "heading": ... }, ... ] }
    is_dynamic = "frames" in meta
    if is_dynamic:
        static_meta = meta.get("static", {})
        frame_meta_list = meta["frames"]
        print(f"Dynamic metadata: {len(frame_meta_list)} frame entries")
    else:
        static_meta = meta
        frame_meta_list = None
    
    def get_frame_meta(frame_idx):
        """Get metadata for the given frame index."""
        if is_dynamic and frame_meta_list:
            idx = min(frame_idx, len(frame_meta_list) - 1)
            fm = frame_meta_list[idx]
            # Merge static and per-frame (per-frame overrides)
            merged = {**static_meta, **fm}
            return merged
        return static_meta

    # 2. Setup Modules
    detector = PersonDetector(model_type=model_type, model_path=model_path, device=device, confidence=yolo_confidence)

    # Initial transformer (will be updated per-frame if metadata is dynamic)
    init_meta = get_frame_meta(0)
    transformer = CoordinateTransformer(
        altitude=init_meta.get("altitude", 50.0),
        fov_h=init_meta.get("fov_h", 60.0),
        fov_v=init_meta.get("fov_v", 45.0),
        img_width=props["width"],
        img_height=props["height"],
        drone_lat=init_meta.get("latitude", 0.0),
        drone_lon=init_meta.get("longitude", 0.0)
    )
    
    heatmap_gen = HeatmapGenerator(width=props["width"], height=props["height"])
    
    # Video Writer for output
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out_video = cv2.VideoWriter(output_path, fourcc, props["fps"], (props["width"], props["height"]))

    csv_output_path = output_path.replace(".mp4", "_headcount.csv")
    csv_file = open(csv_output_path, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["frame_index", "headcount", "headcount_density"])

    # 3. Process Frames
    for frame_idx, frame in ingestor.get_frames():
        # Update transformer if metadata is dynamic (moving drone)
        if is_dynamic:
            fm = get_frame_meta(frame_idx)
            transformer = CoordinateTransformer(
                altitude=fm.get("altitude", 50.0),
                fov_h=fm.get("fov_h", 60.0),
                fov_v=fm.get("fov_v", 45.0),
                img_width=props["width"],
                img_height=props["height"],
                drone_lat=fm.get("latitude", 0.0),
                drone_lon=fm.get("longitude", 0.0)
            )

        # Detect using SDNet density estimation
        ground_points, headcount_density = detector.detect_people(frame)
        
        # Transform (For data accumulation or GIS systems)
        heading = get_frame_meta(frame_idx).get("heading", 0.0)
        gps_coordinates = []
        for point in ground_points:
            gps = transformer.pixel_to_gps(point[0], point[1], drone_heading=heading)
            gps_coordinates.append(gps)
            
        # Draw Heatmap
        heatmap_gen.add_points(ground_points)
        final_frame = heatmap_gen.get_heatmap_overlay(frame)
        
        # Add basic info text
        cv2.putText(final_frame, f"Headcount: {headcount_density:.1f} (Points: {len(ground_points)})", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    
        out_video.write(final_frame)
        csv_writer.writerow([frame_idx, len(ground_points), f"{headcount_density:.2f}"])
        
        if frame_idx % 30 == 0:
            print(f"Processed frame {frame_idx}/{props['frame_count']} "
                  f"(Density Count: {headcount_density:.1f}, Peak Points: {len(ground_points)})")

    # Cleanup
    ingestor.close()
    out_video.release()
    csv_file.close()
    print(f"Pipeline finished. Output saved to {output_path} and {csv_output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drone Video Heatmap Generator")
    parser.add_argument("--video", type=str, required=True, help="Path to input drone video")
    parser.add_argument("--meta", type=str, required=False, default="dronetest_meta.json", help="Path to drone metadata JSON")
    parser.add_argument("--output", type=str, default="output_heatmap.mp4", help="Path to save output video")
    parser.add_argument("--model", type=str, default="sdnet", choices=["sdnet", "yolo"], help="Detector type for crowd density estimation")
    parser.add_argument("--model-path", type=str, default=None, help="Optional path to model weights")
    parser.add_argument("--device", type=str, default=None, help="Computation device: cuda or cpu")
    parser.add_argument("--yolo-confidence", type=float, default=0.35, help="YOLO confidence threshold")

    args = parser.parse_args()

    run_pipeline(
        args.video,
        args.meta,
        args.output,
        model_type=args.model,
        model_path=args.model_path,
        device=args.device,
        yolo_confidence=args.yolo_confidence,
    )
