"""
Paper-oriented evaluation harness for the core UAV mapping pipeline.

This script supports ablations over:
  - pose refinement: raw GPS vs translation-optimized
  - overlap arbitration: basic vs view-aware
  - optional synthetic GPS drift injection

Outputs per run:
  - final_map.png
  - per_frame.csv
  - summary.csv
  - timing / scalability / quality plots

Aggregate outputs:
  - aggregate_summary.csv
  - comparison_table.tex

Usage examples:
    python evaluate_core.py
    python evaluate_core.py --variants raw_basic optimized_view
    python evaluate_core.py --drifts clean gaussian_1m randomwalk_2m
    python evaluate_core.py --datasets data3 --max-frames 80
"""

import argparse
import csv
import glob
import logging
import os
import re
import sys
import time
from datetime import datetime

import cv2
import numpy as np
from scipy.spatial.transform import Rotation as Rot

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.core import MultiBandMap2D, PoseExtractor, PoseGraphOptimizer

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")

DATA1_DIR = os.path.join(BASE_DIR, "data1")
DATA2_DIR = os.path.join(BASE_DIR, "data2")
DATA2_TRAJ = os.path.join(DATA2_DIR, "trajectory.txt")
DATA2_RGB = os.path.join(DATA2_DIR, "rgb")
DATA3_DIR = os.path.join(BASE_DIR, "data3")

MAP_RESOLUTION = 0.5   # m/px
BAND_NUM = 2
TILE_SIZE = 512
MAX_IMG_DIM = 2000

DATA1_FOCAL_MM = 24.0
DATA1_SENSOR_W_MM = 36.0
DATA1_IMG_W = 4000
DATA1_IMG_H = 3000

DATA2_IMG_W = 1920
DATA2_IMG_H = 1080
DATA2_FX = 1220.0
DATA2_FY = 1220.0
DATA2_CX = 960.0
DATA2_CY = 540.0

PG_W_GPS = 9.0
PG_W_MATCH = 0.25
PG_SOLVE_EVERY = 5
PG_MAX_RECENT = 6
PG_MAX_OVERLAP_CANDIDATES = 3
PG_SIFT_FEATURES = 700
PG_SPATIAL_CELL_M = 250.0

VARIANT_CONFIGS = {
    "raw_basic": {
        "use_optimizer": False,
        "arbitration_mode": "basic",
        "label": "Raw GPS + basic overlap",
        "feature_type": "none",
    },
    "raw_view": {
        "use_optimizer": False,
        "arbitration_mode": "view_aware",
        "label": "Raw GPS + view-aware overlap",
        "feature_type": "none",
    },
    "optimized_view_sift": {
        "use_optimizer": True,
        "arbitration_mode": "view_aware",
        "label": "Optimized pose + view-aware overlap (SIFT)",
        "feature_type": "sift",
    },
    "optimized_view_orb": {
        "use_optimizer": True,
        "arbitration_mode": "view_aware",
        "label": "Optimized pose + view-aware overlap (ORB)",
        "feature_type": "orb",
    },
}

DRIFT_CONFIGS = {
    "clean": {"kind": "none", "magnitude_m": 0.0, "seed": 0},
    "gaussian_1m": {"kind": "gaussian", "magnitude_m": 1.0, "seed": 7},
    "gaussian_2m": {"kind": "gaussian", "magnitude_m": 2.0, "seed": 7},
    "randomwalk_2m": {"kind": "random_walk", "magnitude_m": 2.0, "seed": 11},
    "randomwalk_4m": {"kind": "random_walk", "magnitude_m": 4.0, "seed": 11},
    "bias_3m": {"kind": "bias", "magnitude_m": 3.0, "seed": 0},
}

_C_NED_FROM_ENU = np.array(
    [
        [0, 1, 0],
        [1, 0, 0],
        [0, 0, -1],
    ],
    dtype=np.float64,
)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def build_K(fx, fy, cx, cy):
    return np.array(
        [
            [fx, 0, cx],
            [0, fy, cy],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )


def build_K_from_mm(focal_mm, sensor_w_mm, img_w, img_h):
    fx = img_w * (focal_mm / sensor_w_mm)
    fy = fx
    cx = img_w / 2.0
    cy = img_h / 2.0
    return build_K(fx, fy, cx, cy)


def safe_mean(values):
    return float(np.mean(values)) if values else 0.0


def safe_std(values):
    return float(np.std(values)) if values else 0.0


def safe_median(values):
    return float(np.median(values)) if values else 0.0


def safe_min(values):
    return float(np.min(values)) if values else 0.0


def safe_max(values):
    return float(np.max(values)) if values else 0.0


def safe_percentile(values, q):
    return float(np.percentile(values, q)) if values else 0.0


def mkdir(path):
    os.makedirs(path, exist_ok=True)


def slugify(name):
    return name.replace(" ", "_").replace("/", "_")


def extract_capture_time_s(img_path):
    """Best-effort capture timestamp in seconds from supported dataset names."""
    stem = os.path.splitext(os.path.basename(img_path))[0]

    try:
        return float(stem)
    except ValueError:
        pass

    match = re.search(r"DJI_(\d{14})_", stem)
    if match:
        dt = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        return dt.timestamp()

    return None


# ---------------------------------------------------------------------------
# Dataset parsing
# ---------------------------------------------------------------------------
def parse_trajectory(traj_path):
    """
    Parse trajectory.txt lines as:
        timestamp tx ty tz qx qy qz qw

    Returns list of (timestamp_str, pose_4x4) in NED coordinates.
    """
    entries = []
    with open(traj_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            ts = parts[0]
            tx, ty, tz = float(parts[1]), float(parts[2]), float(parts[3])
            qx, qy, qz, qw = float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])

            R_enu = Rot.from_quat([qx, qy, qz, qw]).as_matrix()
            R_ned = _C_NED_FROM_ENU @ R_enu

            T = np.eye(4, dtype=np.float64)
            T[:3, :3] = R_ned
            T[0, 3] = ty
            T[1, 3] = tx
            T[2, 3] = -tz
            entries.append((ts, T))
    return entries


def load_data1(max_frames=None):
    print("\n  Loading data1 (EXIF-based pose)...")
    image_files = sorted(glob.glob(os.path.join(DATA1_DIR, "*.JPG")))
    if not image_files:
        image_files = sorted(glob.glob(os.path.join(DATA1_DIR, "*.jpg")))
    if max_frames:
        image_files = image_files[:max_frames]
    print(f"  Found {len(image_files)} images")

    extractor = PoseExtractor()
    results = []
    skipped = 0
    for img_path in image_files:
        with open(img_path, "rb") as f:
            img_bytes = f.read()
        pose = extractor.extract_pose(img_bytes)
        if pose is not None:
            results.append((img_path, pose))
        else:
            skipped += 1

    print(f"  Loaded {len(results)} poses ({skipped} skipped)")
    return results


def load_data2(max_frames=None):
    print("\n  Loading data2 (external trajectory)...")
    traj_entries = parse_trajectory(DATA2_TRAJ)
    if max_frames:
        traj_entries = traj_entries[:max_frames]
    print(f"  Parsed {len(traj_entries)} trajectory entries")

    results = []
    skipped = 0
    for ts, pose in traj_entries:
        img_path = os.path.join(DATA2_RGB, f"{ts}.jpg")
        if os.path.exists(img_path):
            results.append((img_path, pose))
        else:
            skipped += 1

    print(f"  Matched {len(results)} images ({skipped} missing)")
    return results


def load_data3(max_frames=None):
    print("\n  Loading data3 (EXIF-based pose)...")
    image_files = sorted(glob.glob(os.path.join(DATA3_DIR, "*.JPG")))
    if not image_files:
        image_files = sorted(glob.glob(os.path.join(DATA3_DIR, "*.jpg")))
    image_files = [p for p in image_files if " - Copy" not in os.path.basename(p)]
    if max_frames:
        image_files = image_files[:max_frames]
    print(f"  Found {len(image_files)} images (after filtering copies)")

    extractor = PoseExtractor()
    results = []
    skipped = 0
    for img_path in image_files:
        with open(img_path, "rb") as f:
            img_bytes = f.read()
        pose = extractor.extract_pose(img_bytes)
        if pose is not None:
            results.append((img_path, pose))
        else:
            skipped += 1

    print(f"  Loaded {len(results)} poses ({skipped} skipped)")
    return results


# ---------------------------------------------------------------------------
# Drift injection
# ---------------------------------------------------------------------------
def build_drift_sequence(n_frames, drift_cfg):
    kind = drift_cfg["kind"]
    magnitude = float(drift_cfg.get("magnitude_m", 0.0))
    seed = int(drift_cfg.get("seed", 0))
    if n_frames <= 0:
        return np.zeros((0, 2), dtype=np.float64)
    if kind == "none" or magnitude <= 0:
        return np.zeros((n_frames, 2), dtype=np.float64)

    rng = np.random.default_rng(seed)
    if kind == "gaussian":
        return rng.normal(0.0, magnitude, size=(n_frames, 2))

    if kind == "random_walk":
        steps = rng.normal(0.0, magnitude / 6.0, size=(n_frames, 2))
        drift = np.cumsum(steps, axis=0)
        max_norm = np.max(np.linalg.norm(drift, axis=1))
        if max_norm > 1e-6:
            drift *= magnitude / max_norm
        return drift

    if kind == "bias":
        alpha = np.linspace(0.0, 1.0, n_frames, dtype=np.float64)
        return np.stack([alpha * magnitude, 0.35 * alpha * magnitude], axis=1)

    raise ValueError(f"Unsupported drift kind: {kind}")


def build_pose_records(images_info, drift_name):
    drift_cfg = DRIFT_CONFIGS[drift_name]
    drifts_xy = build_drift_sequence(len(images_info), drift_cfg)
    records = []
    prev_capture_time_s = None
    for idx, ((img_path, pose_ref), drift_xy) in enumerate(zip(images_info, drifts_xy)):
        pose_input = pose_ref.copy()
        pose_input[0, 3] += float(drift_xy[0])
        pose_input[1, 3] += float(drift_xy[1])
        capture_time_s = extract_capture_time_s(img_path)
        inter_frame_interval_s = 0.0
        if capture_time_s is not None and prev_capture_time_s is not None:
            inter_frame_interval_s = max(0.0, float(capture_time_s - prev_capture_time_s))
        if capture_time_s is not None:
            prev_capture_time_s = capture_time_s
        records.append(
            {
                "frame_idx": idx,
                "img_path": img_path,
                "pose_input": pose_input,
                "pose_reference": pose_ref.copy(),
                "capture_time_s": capture_time_s if capture_time_s is not None else 0.0,
                "inter_frame_interval_s": inter_frame_interval_s,
                "drift_x": float(drift_xy[0]),
                "drift_y": float(drift_xy[1]),
                "drift_mag": float(np.linalg.norm(drift_xy)),
            }
        )
    return records


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------
def compute_seam_ssim(mapper):
    """Compute mean SSIM across tile boundaries as a seam quality metric."""
    try:
        img = mapper.render_map(0)
        if img is None or img.shape[0] < 100 or img.shape[1] < 100:
            return 0.0

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        ts = mapper.tile_size
        ssim_scores = []

        for y in range(ts, gray.shape[0] - 10, ts):
            if y + 5 > gray.shape[0]:
                break
            strip_above = gray[max(0, y - 5):y, :].astype(np.float32)
            strip_below = gray[y:min(gray.shape[0], y + 5), :].astype(np.float32)
            if strip_above.shape == strip_below.shape and strip_above.size > 0:
                mu1, mu2 = strip_above.mean(), strip_below.mean()
                if mu1 > 1 and mu2 > 1:
                    s1, s2 = strip_above.std(), strip_below.std()
                    cov = np.mean((strip_above - mu1) * (strip_below - mu2))
                    C1, C2 = 6.5025, 58.5225
                    ssim = ((2 * mu1 * mu2 + C1) * (2 * cov + C2)) / (
                        (mu1 ** 2 + mu2 ** 2 + C1) * (s1 ** 2 + s2 ** 2 + C2)
                    )
                    ssim_scores.append(float(ssim))

        for x in range(ts, gray.shape[1] - 10, ts):
            if x + 5 > gray.shape[1]:
                break
            strip_left = gray[:, max(0, x - 5):x].astype(np.float32)
            strip_right = gray[:, x:min(gray.shape[1], x + 5)].astype(np.float32)
            if strip_left.shape == strip_right.shape and strip_left.size > 0:
                mu1, mu2 = strip_left.mean(), strip_right.mean()
                if mu1 > 1 and mu2 > 1:
                    s1, s2 = strip_left.std(), strip_right.std()
                    cov = np.mean((strip_left - mu1) * (strip_right - mu2))
                    C1, C2 = 6.5025, 58.5225
                    ssim = ((2 * mu1 * mu2 + C1) * (2 * cov + C2)) / (
                        (mu1 ** 2 + mu2 ** 2 + C1) * (s1 ** 2 + s2 ** 2 + C2)
                    )
                    ssim_scores.append(float(ssim))

        return float(np.mean(ssim_scores)) if ssim_scores else 0.0
    except Exception as e:
        logger.error(f"SSIM Error: {e}")
        return 0.0


# ---------------------------------------------------------------------------
# Evaluation core
# ---------------------------------------------------------------------------
def evaluate_dataset(dataset_name, pose_records, K_base, variant_name, drift_name, out_dir):
    """
    Run one dataset/variant/drift combination and collect paper-oriented metrics.
    """
    mkdir(out_dir)
    variant_cfg = VARIANT_CONFIGS[variant_name]
    mapper = MultiBandMap2D(
        resolution=MAP_RESOLUTION,
        band_num=BAND_NUM,
        tile_size=TILE_SIZE,
        arbitration_mode=variant_cfg["arbitration_mode"],
    )
    optimizer = None
    if variant_cfg["use_optimizer"]:
        optimizer = PoseGraphOptimizer(
            w_gps=PG_W_GPS,
            w_match=PG_W_MATCH,
            min_matches=15,
            iou_threshold=0.10,
            solve_every=PG_SOLVE_EVERY,
            max_recent=PG_MAX_RECENT,
            max_overlap_candidates=PG_MAX_OVERLAP_CANDIDATES,
            nfeatures=PG_SIFT_FEATURES,
            spatial_cell_m=PG_SPATIAL_CELL_M,
            feature_type=variant_cfg.get("feature_type", "sift"),
        )

    per_frame = []
    prev_pts = None
    total_bytes = 0
    n_frames = len(pose_records)

    run_label = f"{dataset_name} | {variant_name} | {drift_name}"
    print(f"\n{'=' * 72}")
    print(f"  Evaluating: {run_label}  ({n_frames} frames)")
    print(f"{'=' * 72}")

    for idx, record in enumerate(pose_records):
        t_total = time.perf_counter()
        rec = {
            "frame": idx,
            "variant": variant_name,
            "drift_name": drift_name,
            "use_optimizer": int(variant_cfg["use_optimizer"]),
            "arbitration_mode": variant_cfg["arbitration_mode"],
            "feature_type": variant_cfg.get("feature_type", "none"),
            "capture_time_s": record["capture_time_s"],
            "inter_frame_interval_s": record["inter_frame_interval_s"],
            "drift_x_m": record["drift_x"],
            "drift_y_m": record["drift_y"],
            "drift_mag_m": record["drift_mag"],
        }

        pose_input = record["pose_input"].copy()
        pose_reference = record["pose_reference"].copy()

        t0 = time.perf_counter()
        frame = cv2.imread(record["img_path"], cv2.IMREAD_COLOR)
        rec["decode_ms"] = (time.perf_counter() - t0) * 1000.0
        if frame is None:
            print(f"  [WARN] Could not read {record['img_path']}, skipping.")
            continue

        h, w = frame.shape[:2]
        rec["img_w"] = w
        rec["img_h"] = h
        file_size = os.path.getsize(record["img_path"])
        rec["file_size_bytes"] = file_size
        total_bytes += file_size

        K_frame = K_base.copy()
        t0 = time.perf_counter()
        if max(h, w) > MAX_IMG_DIM:
            scale = MAX_IMG_DIM / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            K_frame[0, 0] *= scale
            K_frame[1, 1] *= scale
            K_frame[0, 2] *= scale
            K_frame[1, 2] *= scale
            rec["downscaled"] = True
            rec["proc_w"] = frame.shape[1]
            rec["proc_h"] = frame.shape[0]
        else:
            rec["downscaled"] = False
            rec["proc_w"] = w
            rec["proc_h"] = h
        rec["downscale_ms"] = (time.perf_counter() - t0) * 1000.0

        pose_eval = pose_input.copy()
        rec["prep_ms"] = 0.0
        rec["optimization_ms"] = 0.0
        rec["correction_x_m"] = 0.0
        rec["correction_y_m"] = 0.0
        rec["correction_mag_m"] = 0.0
        rec["optimizer_edges"] = 0
        rec["edge_residual_before_m"] = 0.0
        rec["edge_residual_after_m"] = 0.0

        raw_xy_error = np.linalg.norm(pose_input[:2, 3] - pose_reference[:2, 3])
        rec["raw_pose_error_m"] = float(raw_xy_error)

        if optimizer is not None:
            t0 = time.perf_counter()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_small = cv2.resize(gray, (gray.shape[1] // 2, gray.shape[0] // 2))
            K_half = K_frame.copy()
            K_half[0, 0] /= 2.0
            K_half[1, 1] /= 2.0
            K_half[0, 2] /= 2.0
            K_half[1, 2] /= 2.0
            rec["prep_ms"] = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            pose_eval = optimizer.add_frame(gray_small, pose_input, K_half)
            rec["optimization_ms"] = (time.perf_counter() - t0) * 1000.0

            corr_xy = pose_eval[:2, 3] - pose_input[:2, 3]
            rec["correction_x_m"] = float(corr_xy[0])
            rec["correction_y_m"] = float(corr_xy[1])
            rec["correction_mag_m"] = float(np.linalg.norm(corr_xy))

            opt_stats = optimizer.get_stats()
            rec["optimizer_edges"] = int(opt_stats["n_edges"])
            rec["edge_residual_before_m"] = float(opt_stats["mean_edge_residual_before"])
            rec["edge_residual_after_m"] = float(opt_stats["mean_edge_residual_after"])

        eval_xy_error = np.linalg.norm(pose_eval[:2, 3] - pose_reference[:2, 3])
        rec["eval_pose_error_m"] = float(eval_xy_error)

        t0 = time.perf_counter()
        success = mapper.feed(frame, pose_eval, K_frame)
        rec["mapping_ms"] = (time.perf_counter() - t0) * 1000.0
        rec["feed_success"] = int(bool(success))
        rec["total_ms"] = (time.perf_counter() - t_total) * 1000.0
        rec["deadline_miss"] = int(
            rec["inter_frame_interval_s"] > 0.0
            and rec["total_ms"] > rec["inter_frame_interval_s"] * 1000.0
        )
        rec["deadline_slack_ms"] = (
            rec["inter_frame_interval_s"] * 1000.0 - rec["total_ms"]
            if rec["inter_frame_interval_s"] > 0.0
            else 0.0
        )

        rec["tile_count"] = len(mapper.tiles)
        rec["memory_bytes"] = mapper.get_memory_usage()
        rec["memory_mb"] = rec["memory_bytes"] / (1024.0 * 1024.0)
        rec["altitude_m"] = float(-pose_eval[2, 3])
        rec["gsd_proxy_m_px"] = float(rec["altitude_m"] * MAP_RESOLUTION) if rec["altitude_m"] > 0 else 0.0

        current_pts = mapper.last_pts_metric
        if prev_pts is not None and current_pts is not None:
            rec["iou"] = float(mapper.calculate_iou(prev_pts, current_pts))
        else:
            rec["iou"] = 0.0
        if current_pts is not None:
            prev_pts = current_pts.copy()

        conflict_stats = mapper.get_conflict_stats()
        rec["conflict_pixels"] = int(conflict_stats["conflict_pixels"])
        rec["conflict_overrides"] = int(conflict_stats["conflict_overrides"])
        rec["new_pixels"] = int(conflict_stats["new_pixels"])
        rec["nonconflict_replacements"] = int(conflict_stats["nonconflict_replacements"])

        per_frame.append(rec)

        if (idx + 1) % 20 == 0 or idx == n_frames - 1:
            print(
                f"  Frame {idx + 1:>4d}/{n_frames} | total={rec['total_ms']:.1f}ms "
                f"map={rec['mapping_ms']:.1f}ms opt={rec['optimization_ms']:.1f}ms "
                f"corr={rec['correction_mag_m']:.2f}m mem={rec['memory_mb']:.1f}MB"
            )

    print("\n  Rendering final map...")
    t0 = time.perf_counter()
    final_map = mapper.render_map(0, show_flight_path=True)
    render_ms = (time.perf_counter() - t0) * 1000.0
    print(f"  Render time: {render_ms:.1f} ms")

    if final_map is not None:
        map_path = os.path.join(out_dir, "final_map.png")
        cv2.imwrite(map_path, final_map)
        print(f"  Saved: {map_path} ({final_map.shape[1]}x{final_map.shape[0]} px)")

    print("  Computing seam SSIM...")
    seam_ssim = compute_seam_ssim(mapper)
    print(f"  Seam SSIM: {seam_ssim:.4f}")

    coverage = mapper.get_coverage_data()
    area_m2 = coverage["area_m2"]
    print(f"  Coverage area: {area_m2:.1f} m^2")

    feed_ok = [r for r in per_frame if r["feed_success"]]
    decode_times = [r["decode_ms"] for r in per_frame]
    downscale_times = [r["downscale_ms"] for r in per_frame]
    prep_times = [r["prep_ms"] for r in per_frame]
    optimization_times = [r["optimization_ms"] for r in per_frame]
    mapping_times = [r["mapping_ms"] for r in per_frame]
    total_times = [r["total_ms"] for r in per_frame]
    capture_intervals = [r["inter_frame_interval_s"] for r in per_frame if r["inter_frame_interval_s"] > 0.0]
    deadline_rows = [r for r in per_frame if r["inter_frame_interval_s"] > 0.0]
    deadline_misses = [r["deadline_miss"] for r in deadline_rows]
    deadline_slacks = [r["deadline_slack_ms"] for r in deadline_rows]
    ious = [r["iou"] for r in per_frame if r["iou"] > 0]
    raw_errors = [r["raw_pose_error_m"] for r in per_frame]
    eval_errors = [r["eval_pose_error_m"] for r in per_frame]
    correction_mags = [r["correction_mag_m"] for r in per_frame]
    altitudes = [r["altitude_m"] for r in per_frame]
    edge_before = [r["edge_residual_before_m"] for r in per_frame if r["edge_residual_before_m"] > 0]
    edge_after = [r["edge_residual_after_m"] for r in per_frame if r["edge_residual_after_m"] > 0]
    memory_final = per_frame[-1]["memory_mb"] if per_frame else 0.0
    tile_final = per_frame[-1]["tile_count"] if per_frame else 0
    conflict_stats = mapper.get_conflict_stats()
    optimizer_residuals = optimizer.get_residual_stats() if optimizer is not None else None

    queue_delay_s = 0.0
    max_queue_delay_s = 0.0
    for r in deadline_rows:
        queue_delay_s = max(
            0.0,
            queue_delay_s + (r["total_ms"] / 1000.0) - r["inter_frame_interval_s"],
        )
        max_queue_delay_s = max(max_queue_delay_s, queue_delay_s)

    summary = {
        "dataset": dataset_name,
        "variant": variant_name,
        "variant_label": variant_cfg["label"],
        "drift_name": drift_name,
        "drift_kind": DRIFT_CONFIGS[drift_name]["kind"],
        "drift_magnitude_m": DRIFT_CONFIGS[drift_name]["magnitude_m"],
        "use_optimizer": int(variant_cfg["use_optimizer"]),
        "arbitration_mode": variant_cfg["arbitration_mode"],
        "feature_type": variant_cfg.get("feature_type", "none"),
        "n_frames": len(per_frame),
        "n_successful_feeds": len(feed_ok),
        "total_input_mb": total_bytes / (1024.0 * 1024.0),
        "avg_decode_ms": safe_mean(decode_times),
        "avg_downscale_ms": safe_mean(downscale_times),
        "avg_prep_ms": safe_mean(prep_times),
        "avg_optimization_ms": safe_mean(optimization_times),
        "avg_mapping_ms": safe_mean(mapping_times),
        "avg_total_ms": safe_mean(total_times),
        "std_total_ms": safe_std(total_times),
        "median_total_ms": safe_median(total_times),
        "p95_total_ms": safe_percentile(total_times, 95),
        "throughput_fps_total": (1000.0 / safe_mean(total_times)) if total_times and safe_mean(total_times) > 0 else 0.0,
        "mean_capture_interval_s": safe_mean(capture_intervals),
        "median_capture_interval_s": safe_median(capture_intervals),
        "capture_fps_mean": (1.0 / safe_mean(capture_intervals)) if capture_intervals and safe_mean(capture_intervals) > 0 else 0.0,
        "avg_deadline_slack_ms": safe_mean(deadline_slacks),
        "p05_deadline_slack_ms": safe_percentile(deadline_slacks, 5),
        "deadline_miss_rate": safe_mean(deadline_misses),
        "max_queue_delay_s": max_queue_delay_s,
        "avg_feed_ms_legacy": safe_mean(mapping_times),
        "render_ms": render_ms,
        "tile_count": tile_final,
        "memory_mb": memory_final,
        "avg_iou": safe_mean(ious),
        "std_iou": safe_std(ious),
        "seam_ssim": seam_ssim,
        "coverage_m2": area_m2,
        "avg_altitude_m": safe_mean(altitudes),
        "avg_raw_pose_error_m": safe_mean(raw_errors),
        "avg_eval_pose_error_m": safe_mean(eval_errors),
        "median_eval_pose_error_m": safe_median(eval_errors),
        "avg_correction_mag_m": safe_mean(correction_mags),
        "max_correction_mag_m": safe_max(correction_mags),
        "p95_correction_mag_m": safe_percentile(correction_mags, 95),
        "frames_with_nonzero_correction": int(sum(1 for v in correction_mags if v > 1e-6)),
        "avg_edge_residual_before_m": safe_mean(edge_before),
        "avg_edge_residual_after_m": safe_mean(edge_after),
        "conflict_pixels": int(conflict_stats["conflict_pixels"]),
        "conflict_overrides": int(conflict_stats["conflict_overrides"]),
        "new_pixels": int(conflict_stats["new_pixels"]),
        "nonconflict_replacements": int(conflict_stats["nonconflict_replacements"]),
        "map_w_px": final_map.shape[1] if final_map is not None else 0,
        "map_h_px": final_map.shape[0] if final_map is not None else 0,
    }

    if optimizer_residuals is not None:
        summary["optimizer_edge_count"] = optimizer_residuals["count"]
        summary["optimizer_mean_edge_before_m"] = optimizer_residuals["mean_before"]
        summary["optimizer_mean_edge_after_m"] = optimizer_residuals["mean_after"]
        summary["optimizer_median_edge_before_m"] = optimizer_residuals["median_before"]
        summary["optimizer_median_edge_after_m"] = optimizer_residuals["median_after"]
        summary["optimizer_max_edge_before_m"] = optimizer_residuals["max_before"]
        summary["optimizer_max_edge_after_m"] = optimizer_residuals["max_after"]
    else:
        summary["optimizer_edge_count"] = 0
        summary["optimizer_mean_edge_before_m"] = 0.0
        summary["optimizer_mean_edge_after_m"] = 0.0
        summary["optimizer_median_edge_before_m"] = 0.0
        summary["optimizer_median_edge_after_m"] = 0.0
        summary["optimizer_max_edge_before_m"] = 0.0
        summary["optimizer_max_edge_after_m"] = 0.0

    if per_frame:
        csv_path = os.path.join(out_dir, "per_frame.csv")
        keys = sorted({key for row in per_frame for key in row.keys()})
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(per_frame)
        print(f"  Per-frame data: {csv_path}")

    sum_path = os.path.join(out_dir, "summary.csv")
    with open(sum_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)
    print(f"  Summary: {sum_path}")

    generate_plots(per_frame, summary, out_dir)
    return summary, per_frame


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def generate_plots(per_frame, summary, out_dir):
    """Generate publication-friendly plots."""
    if not per_frame:
        return

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "axes.grid": True,
            "grid.alpha": 0.3,
        }
    )

    title_stub = f"{summary['dataset']} | {summary['variant']} | {summary['drift_name']}"
    frames = [r["frame"] for r in per_frame]

    fig, ax = plt.subplots(figsize=(8, 3.6))
    total_ms = [r["total_ms"] for r in per_frame]
    map_ms = [r["mapping_ms"] for r in per_frame]
    opt_ms = [r["optimization_ms"] for r in per_frame]
    ax.plot(frames, total_ms, linewidth=1.1, color="#1d4ed8", label="Total")
    ax.plot(frames, map_ms, linewidth=0.9, color="#059669", label="Mapping")
    if any(v > 0 for v in opt_ms):
        ax.plot(frames, opt_ms, linewidth=0.9, color="#dc2626", label="Optimization")
    ax.set_xlabel("Frame Index")
    ax.set_ylabel("Time (ms)")
    ax.set_title(f"Per-frame latency | {title_stub}")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend()
    fig.savefig(os.path.join(out_dir, "timing_plot.png"))
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(8, 3.6))
    tiles = [r["tile_count"] for r in per_frame]
    mem = [r["memory_mb"] for r in per_frame]
    ax1.plot(frames, tiles, linewidth=1.5, color="#0f766e", label="Tile count")
    ax1.set_xlabel("Frame Index")
    ax1.set_ylabel("Tile Count", color="#0f766e")
    ax1.tick_params(axis="y", labelcolor="#0f766e")
    ax2 = ax1.twinx()
    ax2.plot(frames, mem, linewidth=1.5, color="#7c3aed", linestyle="--", label="Memory (MB)")
    ax2.set_ylabel("Memory (MB)", color="#7c3aed")
    ax2.tick_params(axis="y", labelcolor="#7c3aed")
    ax1.set_title(f"Scalability | {title_stub}")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    fig.savefig(os.path.join(out_dir, "scalability_plot.png"))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.4))
    ious = [r["iou"] for r in per_frame]
    ax.plot(frames, ious, linewidth=1.0, color="#d97706", marker=".", markersize=3)
    if any(v > 0 for v in ious):
        ax.axhline(y=summary["avg_iou"], color="#991b1b", linestyle="--", linewidth=1, label=f"Mean = {summary['avg_iou']:.3f}")
        ax.legend()
    ax.set_xlabel("Frame Index")
    ax.set_ylabel("IoU")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title(f"Consecutive footprint IoU | {title_stub}")
    fig.savefig(os.path.join(out_dir, "iou_plot.png"))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.3))
    raw_err = [r["raw_pose_error_m"] for r in per_frame]
    eval_err = [r["eval_pose_error_m"] for r in per_frame]
    ax.plot(frames, raw_err, linewidth=1.0, color="#94a3b8", label="Input pose error")
    ax.plot(frames, eval_err, linewidth=1.2, color="#2563eb", label="Evaluated pose error")
    ax.set_xlabel("Frame Index")
    ax.set_ylabel("Position error to clean pose (m)")
    ax.set_title(f"Translation error vs clean reference | {title_stub}")
    ax.legend()
    fig.savefig(os.path.join(out_dir, "pose_error_plot.png"))
    plt.close(fig)

    if summary["use_optimizer"]:
        fig, ax = plt.subplots(figsize=(8, 3.3))
        corr = [r["correction_mag_m"] for r in per_frame]
        ax.plot(frames, corr, linewidth=1.1, color="#b45309", label="Correction magnitude")
        ax.set_xlabel("Frame Index")
        ax.set_ylabel("Correction (m)")
        ax.set_title(f"Pose-graph correction magnitude | {title_stub}")
        ax.legend()
        fig.savefig(os.path.join(out_dir, "correction_plot.png"))
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(8, 3.3))
        edge_before = [r["edge_residual_before_m"] for r in per_frame]
        edge_after = [r["edge_residual_after_m"] for r in per_frame]
        ax.plot(frames, edge_before, linewidth=1.0, color="#9ca3af", label="Before")
        ax.plot(frames, edge_after, linewidth=1.0, color="#059669", label="After")
        ax.set_xlabel("Frame Index")
        ax.set_ylabel("Mean edge residual (m)")
        ax.set_title(f"Visual-consistency residuals | {title_stub}")
        ax.legend()
        fig.savefig(os.path.join(out_dir, "residual_plot.png"))
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.3))
    conflict = [r["conflict_pixels"] for r in per_frame]
    overrides = [r["conflict_overrides"] for r in per_frame]
    ax.plot(frames, conflict, linewidth=1.0, color="#7c2d12", label="Conflict pixels")
    ax.plot(frames, overrides, linewidth=1.0, color="#1d4ed8", label="Conflict overrides")
    ax.set_xlabel("Frame Index")
    ax.set_ylabel("Cumulative pixels")
    ax.set_title(f"Overlap arbitration activity | {title_stub}")
    ax.legend()
    fig.savefig(os.path.join(out_dir, "arbitration_plot.png"))
    plt.close(fig)

    print(f"  Plots saved to {out_dir}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_summary(summary):
    print(f"\n  {'-' * 60}")
    print(f"  Summary: {summary['dataset']} | {summary['variant']} | {summary['drift_name']}")
    print(f"  {'-' * 60}")
    print(f"  Frames processed:      {summary['n_frames']}")
    print(f"  Successful feeds:      {summary['n_successful_feeds']}")
    print(f"  Throughput (total):    {summary['throughput_fps_total']:.2f} FPS")
    if summary.get("mean_capture_interval_s", 0.0) > 0:
        print(f"  Capture rate:          {summary['capture_fps_mean']:.2f} FPS")
        print(f"  Avg deadline slack:    {summary['avg_deadline_slack_ms']:.1f} ms")
        print(f"  Deadline miss rate:    {summary['deadline_miss_rate'] * 100.0:.1f}%")
    print(f"  Avg total latency:     {summary['avg_total_ms']:.2f} ms")
    print(f"  Avg optimization:      {summary['avg_optimization_ms']:.2f} ms")
    print(f"  Avg mapping:           {summary['avg_mapping_ms']:.2f} ms")
    print(f"  Final memory:          {summary['memory_mb']:.1f} MB")
    print(f"  Avg raw pose error:    {summary['avg_raw_pose_error_m']:.3f} m")
    print(f"  Avg eval pose error:   {summary['avg_eval_pose_error_m']:.3f} m")
    print(f"  Avg correction mag:    {summary['avg_correction_mag_m']:.3f} m")
    print(f"  Avg edge residual:     {summary['avg_edge_residual_before_m']:.3f} -> {summary['avg_edge_residual_after_m']:.3f} m")
    print(f"  Seam SSIM:             {summary['seam_ssim']:.4f}")
    print(f"  Coverage:              {summary['coverage_m2']:.1f} m^2")
    print(f"  Conflict overrides:    {summary['conflict_overrides']}")
    print(f"  Map size:              {summary['map_w_px']}x{summary['map_h_px']} px")
    print(f"  {'-' * 60}")


def write_aggregate_summary(summaries, out_path):
    if not summaries:
        return
    keys = sorted({key for row in summaries for key in row.keys()})
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(summaries)
    print(f"\n  Aggregate CSV: {out_path}")


def generate_comparison_table(summaries, out_path):
    if not summaries:
        return ""

    grouped = {}
    for row in summaries:
        grouped.setdefault((row["dataset"], row["drift_name"]), []).append(row)

    lines = []
    for (dataset, drift_name), rows in grouped.items():
        rows = sorted(rows, key=lambda r: r["variant"])
        best_fps = max(row["throughput_fps_total"] for row in rows)
        best_total_ms = min(row["avg_total_ms"] for row in rows)
        best_pose_err = min(row["avg_eval_pose_error_m"] for row in rows)
        best_seam = max(row["seam_ssim"] for row in rows)
        best_edge_after = min(row["avg_edge_residual_after_m"] for row in rows)

        def fmt(value, best_value, higher_is_better=False, digits=2):
            is_best = value == best_value
            text = f"{value:.{digits}f}"
            return rf"\textbf{{{text}}}" if is_best else text

        lines.append(r"\begin{table}[htbp]")
        lines.append(r"\centering")
        lines.append(rf"\caption{{Full-dataset evaluation variants on {dataset} ({drift_name})}}")
        lines.append(rf"\label{{tab:{slugify(dataset)}_{slugify(drift_name)}}}")
        lines.append(r"\begin{tabular}{lrrrrrr}")
        lines.append(r"\toprule")
        lines.append(r"Variant & FPS & Total ms & Pose err (m) & Corr (m) & Seam SSIM & Edge after (m) \\")
        lines.append(r"\midrule")
        for row in rows:
            lines.append(
                f"{row['variant']} & "
                f"{fmt(row['throughput_fps_total'], best_fps, higher_is_better=True, digits=2)} & "
                f"{fmt(row['avg_total_ms'], best_total_ms, digits=2)} & "
                f"{fmt(row['avg_eval_pose_error_m'], best_pose_err, digits=3)} & "
                f"{row['avg_correction_mag_m']:.3f} & "
                f"{fmt(row['seam_ssim'], best_seam, higher_is_better=True, digits=4)} & "
                f"{fmt(row['avg_edge_residual_after_m'], best_edge_after, digits=3)} \\\\"
            )
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append(r"\end{table}")
        lines.append("")

    tex = "\n".join(lines)
    with open(out_path, "w") as f:
        f.write(tex)
    print(f"  LaTeX table: {out_path}")
    return tex


# ---------------------------------------------------------------------------
# CLI / orchestration
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Run paper-oriented mapping experiments.")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["data1", "data2", "data3"],
        choices=["data1", "data2", "data3"],
        help="Datasets to evaluate.",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["raw_basic", "raw_view", "optimized_view_sift", "optimized_view_orb"],
        choices=sorted(VARIANT_CONFIGS.keys()),
        help="Method variants to evaluate.",
    )
    parser.add_argument(
        "--drifts",
        nargs="+",
        default=["clean"],
        choices=sorted(DRIFT_CONFIGS.keys()),
        help="Drift scenarios to evaluate.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional cap on loaded frames per dataset.",
    )
    return parser.parse_args()


def load_dataset(dataset_name, max_frames=None):
    if dataset_name == "data1":
        images = load_data1(max_frames=max_frames)
        K = build_K_from_mm(DATA1_FOCAL_MM, DATA1_SENSOR_W_MM, DATA1_IMG_W, DATA1_IMG_H)
        return images, K
    if dataset_name == "data2":
        images = load_data2(max_frames=max_frames)
        K = build_K(DATA2_FX, DATA2_FY, DATA2_CX, DATA2_CY)
        return images, K
    if dataset_name == "data3":
        images = load_data3(max_frames=max_frames)
        K = build_K_from_mm(DATA1_FOCAL_MM, DATA1_SENSOR_W_MM, DATA1_IMG_W, DATA1_IMG_H)
        return images, K
    raise ValueError(f"Unsupported dataset: {dataset_name}")


def main():
    args = parse_args()
    mkdir(RESULTS_DIR)

    print("=" * 72)
    print("  Core Backend System -- Paper Evaluation Harness")
    print("=" * 72)

    all_summaries = []

    for dataset_name in args.datasets:
        images_info, K_base = load_dataset(dataset_name, max_frames=args.max_frames)
        if not images_info:
            print(f"  [SKIP] {dataset_name} -- no usable images found")
            continue

        for drift_name in args.drifts:
            pose_records = build_pose_records(images_info, drift_name)
            for variant_name in args.variants:
                out_dir = os.path.join(RESULTS_DIR, dataset_name, drift_name, variant_name)
                summary, _ = evaluate_dataset(
                    dataset_name=dataset_name,
                    pose_records=pose_records,
                    K_base=K_base,
                    variant_name=variant_name,
                    drift_name=drift_name,
                    out_dir=out_dir,
                )
                print_summary(summary)
                all_summaries.append(summary)

    aggregate_csv = os.path.join(RESULTS_DIR, "aggregate_summary.csv")
    write_aggregate_summary(all_summaries, aggregate_csv)

    tex_path = os.path.join(RESULTS_DIR, "comparison_table.tex")
    tex = generate_comparison_table(all_summaries, tex_path)
    if tex:
        print(f"\n  LaTeX table content:\n\n{tex}")

    print(f"\n{'=' * 72}")
    print(f"  Evaluation complete. Results in: {RESULTS_DIR}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
