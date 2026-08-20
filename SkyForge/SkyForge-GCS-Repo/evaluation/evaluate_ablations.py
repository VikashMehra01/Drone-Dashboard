"""
Hyperparameter ablation study for the ISPRS paper.

Sweeps:
  1. w_gps:       {1.0, 3.0, 9.0, 27.0}    on data1/bias_3m/ORB
  2. w_match:     {0.05, 0.10, 0.25, 0.50}  on data1/bias_3m/ORB  (w_gps fixed=9.0)
  3. nfeatures:   {200, 500, 700, 1000}      on data1/clean/ORB
  4. solve_every: {1, 3, 5, 10}              on data1/clean/ORB

Each sweep fixes all other parameters at default values and varies one.
Outputs per run:  summary.csv
Aggregate output: results/ablation_summary.csv, results/ablation_tables.tex
"""

import csv
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_core import (
    BASE_DIR,
    RESULTS_DIR,
    MAP_RESOLUTION,
    BAND_NUM,
    TILE_SIZE,
    MAX_IMG_DIM,
    PG_W_GPS,
    PG_W_MATCH,
    PG_SOLVE_EVERY,
    PG_MAX_RECENT,
    PG_MAX_OVERLAP_CANDIDATES,
    PG_SIFT_FEATURES,
    PG_SPATIAL_CELL_M,
    DRIFT_CONFIGS,
    build_drift_sequence,
    build_pose_records,
    compute_seam_ssim,
    extract_capture_time_s,
    load_data1,
    build_K_from_mm,
    DATA1_FOCAL_MM,
    DATA1_SENSOR_W_MM,
    DATA1_IMG_W,
    DATA1_IMG_H,
    mkdir,
    safe_mean,
    safe_std,
    safe_median,
    safe_max,
    safe_percentile,
)
from backend.core import MultiBandMap2D, PoseGraphOptimizer


def run_one(pose_records, K_base, optimizer_params, arbitration_mode, label, out_dir):
    """Run a single ablation configuration and return summary dict."""
    mkdir(out_dir)

    mapper = MultiBandMap2D(
        resolution=MAP_RESOLUTION,
        band_num=BAND_NUM,
        tile_size=TILE_SIZE,
        arbitration_mode=arbitration_mode,
    )

    optimizer = None
    if optimizer_params is not None:
        optimizer = PoseGraphOptimizer(**optimizer_params)

    per_frame = []
    prev_pts = None
    n_frames = len(pose_records)
    print(f"\n  [{label}] ({n_frames} frames) -> {out_dir}")

    for idx, record in enumerate(pose_records):
        t_total = time.perf_counter()
        pose_input = record["pose_input"].copy()
        pose_reference = record["pose_reference"].copy()

        frame = cv2.imread(record["img_path"], cv2.IMREAD_COLOR)
        if frame is None:
            continue
        h, w = frame.shape[:2]

        K_frame = K_base.copy()
        if max(h, w) > MAX_IMG_DIM:
            scale = MAX_IMG_DIM / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
            K_frame[0, 0] *= scale
            K_frame[1, 1] *= scale
            K_frame[0, 2] *= scale
            K_frame[1, 2] *= scale

        pose_eval = pose_input.copy()
        optimization_ms = 0.0
        correction_mag = 0.0
        edge_res_before = 0.0
        edge_res_after = 0.0
        n_edges = 0

        if optimizer is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_small = cv2.resize(gray, (gray.shape[1] // 2, gray.shape[0] // 2))
            K_half = K_frame.copy()
            K_half[0, :] /= 2.0
            K_half[1, :] /= 2.0

            t0 = time.perf_counter()
            pose_eval = optimizer.add_frame(gray_small, pose_input, K_half)
            optimization_ms = (time.perf_counter() - t0) * 1000.0

            corr_xy = pose_eval[:2, 3] - pose_input[:2, 3]
            correction_mag = float(np.linalg.norm(corr_xy))
            stats = optimizer.get_stats()
            n_edges = int(stats["n_edges"])
            edge_res_before = float(stats["mean_edge_residual_before"])
            edge_res_after = float(stats["mean_edge_residual_after"])

        t0 = time.perf_counter()
        mapper.feed(frame, pose_eval, K_frame)
        mapping_ms = (time.perf_counter() - t0) * 1000.0

        total_ms = (time.perf_counter() - t_total) * 1000.0
        raw_err = float(np.linalg.norm(pose_input[:2, 3] - pose_reference[:2, 3]))
        eval_err = float(np.linalg.norm(pose_eval[:2, 3] - pose_reference[:2, 3]))

        per_frame.append({
            "frame": idx,
            "total_ms": total_ms,
            "mapping_ms": mapping_ms,
            "optimization_ms": optimization_ms,
            "correction_mag_m": correction_mag,
            "raw_pose_error_m": raw_err,
            "eval_pose_error_m": eval_err,
            "edge_residual_before_m": edge_res_before,
            "edge_residual_after_m": edge_res_after,
            "n_edges": n_edges,
            "memory_mb": mapper.get_memory_usage() / (1024.0 * 1024.0),
        })

        if (idx + 1) % 60 == 0 or idx == n_frames - 1:
            print(f"    Frame {idx+1:>4d}/{n_frames} | "
                  f"total={total_ms:.0f}ms opt={optimization_ms:.0f}ms "
                  f"corr={correction_mag:.3f}m err={eval_err:.3f}m")

    # Aggregate
    seam_ssim = compute_seam_ssim(mapper)
    total_times = [r["total_ms"] for r in per_frame]
    opt_times = [r["optimization_ms"] for r in per_frame]
    map_times = [r["mapping_ms"] for r in per_frame]
    corrections = [r["correction_mag_m"] for r in per_frame]
    raw_errors = [r["raw_pose_error_m"] for r in per_frame]
    eval_errors = [r["eval_pose_error_m"] for r in per_frame]
    edge_before = [r["edge_residual_before_m"] for r in per_frame if r["edge_residual_before_m"] > 0]
    edge_after = [r["edge_residual_after_m"] for r in per_frame if r["edge_residual_after_m"] > 0]

    opt_residuals = optimizer.get_residual_stats() if optimizer is not None else None

    summary = {
        "label": label,
        "n_frames": len(per_frame),
        "avg_total_ms": safe_mean(total_times),
        "p95_total_ms": safe_percentile(total_times, 95),
        "avg_optimization_ms": safe_mean(opt_times),
        "avg_mapping_ms": safe_mean(map_times),
        "throughput_fps": 1000.0 / safe_mean(total_times) if total_times and safe_mean(total_times) > 0 else 0,
        "avg_raw_pose_error_m": safe_mean(raw_errors),
        "avg_eval_pose_error_m": safe_mean(eval_errors),
        "avg_correction_mag_m": safe_mean(corrections),
        "max_correction_mag_m": safe_max(corrections),
        "seam_ssim": seam_ssim,
        "n_edges": per_frame[-1]["n_edges"] if per_frame else 0,
        "avg_edge_residual_before_m": safe_mean(edge_before),
        "avg_edge_residual_after_m": safe_mean(edge_after),
        "memory_mb": per_frame[-1]["memory_mb"] if per_frame else 0,
    }

    if opt_residuals is not None:
        summary["optimizer_edge_count"] = opt_residuals["count"]
        summary["optimizer_mean_edge_before_m"] = opt_residuals["mean_before"]
        summary["optimizer_mean_edge_after_m"] = opt_residuals["mean_after"]
    else:
        summary["optimizer_edge_count"] = 0
        summary["optimizer_mean_edge_before_m"] = 0.0
        summary["optimizer_mean_edge_after_m"] = 0.0

    # Save summary CSV
    sum_path = os.path.join(out_dir, "summary.csv")
    with open(sum_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    print(f"    => FPS={summary['throughput_fps']:.2f}  "
          f"opt={summary['avg_optimization_ms']:.0f}ms  "
          f"corr={summary['avg_correction_mag_m']:.3f}m  "
          f"err={summary['avg_eval_pose_error_m']:.3f}m  "
          f"SSIM={summary['seam_ssim']:.4f}  "
          f"edges={summary['n_edges']}")

    return summary


def default_optimizer_params(feature_type="orb"):
    return {
        "w_gps": PG_W_GPS,
        "w_match": PG_W_MATCH,
        "min_matches": 15,
        "iou_threshold": 0.10,
        "solve_every": PG_SOLVE_EVERY,
        "max_recent": PG_MAX_RECENT,
        "max_overlap_candidates": PG_MAX_OVERLAP_CANDIDATES,
        "nfeatures": PG_SIFT_FEATURES,
        "spatial_cell_m": PG_SPATIAL_CELL_M,
        "feature_type": feature_type,
    }


def main():
    print("=" * 72)
    print("  Hyperparameter Ablation Study")
    print("=" * 72)

    # Load data1
    images_info, K_base = load_data1(), build_K_from_mm(
        DATA1_FOCAL_MM, DATA1_SENSOR_W_MM, DATA1_IMG_W, DATA1_IMG_H
    )
    images_info_data1 = images_info

    pose_records_clean = build_pose_records(images_info_data1, "clean")
    pose_records_bias = build_pose_records(images_info_data1, "bias_3m")

    all_summaries = []
    ablation_dir = os.path.join(RESULTS_DIR, "ablations")
    mkdir(ablation_dir)

    # ===================================================================
    # Sweep 1: w_gps  (on data1 / bias_3m / ORB)
    # ===================================================================
    print("\n" + "=" * 72)
    print("  SWEEP 1: w_gps  (data1 / bias_3m / ORB)")
    print("=" * 72)

    w_gps_values = [1.0, 3.0, 9.0, 27.0]
    for w_gps in w_gps_values:
        params = default_optimizer_params("orb")
        params["w_gps"] = w_gps
        label = f"w_gps={w_gps}"
        out_dir = os.path.join(ablation_dir, "w_gps", f"{w_gps:.1f}")
        s = run_one(pose_records_bias, K_base, params, "view_aware", label, out_dir)
        s["sweep"] = "w_gps"
        s["sweep_value"] = w_gps
        s["drift"] = "bias_3m"
        all_summaries.append(s)

    # ===================================================================
    # Sweep 2: w_match  (on data1 / bias_3m / ORB, w_gps fixed=9.0)
    # ===================================================================
    print("\n" + "=" * 72)
    print("  SWEEP 2: w_match  (data1 / bias_3m / ORB)")
    print("=" * 72)

    w_match_values = [0.05, 0.10, 0.25, 0.50, 1.00]
    for w_match in w_match_values:
        params = default_optimizer_params("orb")
        params["w_match"] = w_match
        label = f"w_match={w_match}"
        out_dir = os.path.join(ablation_dir, "w_match", f"{w_match:.2f}")
        s = run_one(pose_records_bias, K_base, params, "view_aware", label, out_dir)
        s["sweep"] = "w_match"
        s["sweep_value"] = w_match
        s["drift"] = "bias_3m"
        all_summaries.append(s)

    # ===================================================================
    # Sweep 3: nfeatures  (on data1 / clean / ORB)
    # ===================================================================
    print("\n" + "=" * 72)
    print("  SWEEP 3: nfeatures  (data1 / clean / ORB)")
    print("=" * 72)

    nfeatures_values = [200, 500, 700, 1000]
    for nf in nfeatures_values:
        params = default_optimizer_params("orb")
        params["nfeatures"] = nf
        label = f"nfeatures={nf}"
        out_dir = os.path.join(ablation_dir, "nfeatures", str(nf))
        s = run_one(pose_records_clean, K_base, params, "view_aware", label, out_dir)
        s["sweep"] = "nfeatures"
        s["sweep_value"] = nf
        s["drift"] = "clean"
        all_summaries.append(s)

    # ===================================================================
    # Sweep 4: solve_every  (on data1 / clean / ORB)
    # ===================================================================
    print("\n" + "=" * 72)
    print("  SWEEP 4: solve_every  (data1 / clean / ORB)")
    print("=" * 72)

    solve_values = [1, 3, 5, 10]
    for sv in solve_values:
        params = default_optimizer_params("orb")
        params["solve_every"] = sv
        label = f"solve_every={sv}"
        out_dir = os.path.join(ablation_dir, "solve_every", str(sv))
        s = run_one(pose_records_clean, K_base, params, "view_aware", label, out_dir)
        s["sweep"] = "solve_every"
        s["sweep_value"] = sv
        s["drift"] = "clean"
        all_summaries.append(s)

    # ===================================================================
    # Sweep 5: nfeatures  (on data1 / clean / SIFT)  — for ORB vs SIFT comparison
    # ===================================================================
    print("\n" + "=" * 72)
    print("  SWEEP 5: nfeatures  (data1 / clean / SIFT)")
    print("=" * 72)

    for nf in nfeatures_values:
        params = default_optimizer_params("sift")
        params["nfeatures"] = nf
        label = f"sift_nfeatures={nf}"
        out_dir = os.path.join(ablation_dir, "nfeatures_sift", str(nf))
        s = run_one(pose_records_clean, K_base, params, "view_aware", label, out_dir)
        s["sweep"] = "nfeatures_sift"
        s["sweep_value"] = nf
        s["drift"] = "clean"
        all_summaries.append(s)

    # ===================================================================
    # Save aggregate
    # ===================================================================
    agg_path = os.path.join(ablation_dir, "ablation_summary.csv")
    if all_summaries:
        keys = list(all_summaries[0].keys())
        for s in all_summaries[1:]:
            for k in s:
                if k not in keys:
                    keys.append(k)
        with open(agg_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_summaries)
        print(f"\n  Aggregate ablation CSV: {agg_path}")

    # ===================================================================
    # Generate LaTeX tables
    # ===================================================================
    generate_ablation_tables(all_summaries, ablation_dir)

    print(f"\n{'=' * 72}")
    print(f"  Ablation study complete. Results in: {ablation_dir}")
    print(f"{'=' * 72}")


def generate_ablation_tables(summaries, out_dir):
    """Generate ablation LaTeX tables."""
    if not summaries:
        return

    lines = []

    # --- Table: w_gps sweep ---
    w_gps_rows = [s for s in summaries if s["sweep"] == "w_gps"]
    if w_gps_rows:
        lines.append(r"% w_gps sensitivity (data1, bias_3m, ORB)")
        lines.append(r"\begin{table}[t]")
        lines.append(r"\centering")
        lines.append(r"\caption{Effect of GPS prior weight $w_\text{gps}$ on correction")
        lines.append(r"         behaviour under 3\,m synthetic bias (data1, ORB detector,")
        lines.append(r"         $w_\text{match}=0.25$ fixed).}")
        lines.append(r"\label{tab:ablation_wgps}")
        lines.append(r"\begin{tabular}{r rrrr r}")
        lines.append(r"\toprule")
        lines.append(r"$w_\text{gps}$")
        lines.append(r"  & \parbox{0.9cm}{\centering Avg\\corr (m)}")
        lines.append(r"  & \parbox{0.9cm}{\centering Eval\\err (m)}")
        lines.append(r"  & \parbox{0.9cm}{\centering Res.\\before}")
        lines.append(r"  & \parbox{0.9cm}{\centering Res.\\after}")
        lines.append(r"  & \parbox{0.9cm}{\centering Seam\\SSIM} \\")
        lines.append(r"\midrule")
        for r in w_gps_rows:
            lines.append(
                f"  {r['sweep_value']:.0f} & "
                f"{r['avg_correction_mag_m']:.3f} & "
                f"{r['avg_eval_pose_error_m']:.3f} & "
                f"{r['optimizer_mean_edge_before_m']:.2f} & "
                f"{r['optimizer_mean_edge_after_m']:.2f} & "
                f"{r['seam_ssim']:.4f} \\\\"
            )
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append(r"\end{table}")
        lines.append("")

    # --- Table: w_match sweep ---
    w_match_rows = [s for s in summaries if s["sweep"] == "w_match"]
    if w_match_rows:
        lines.append(r"% w_match sensitivity (data1, bias_3m, ORB)")
        lines.append(r"\begin{table}[t]")
        lines.append(r"\centering")
        lines.append(r"\caption{Effect of match weight $w_\text{match}$ on correction")
        lines.append(r"         behaviour under 3\,m synthetic bias (data1, ORB detector,")
        lines.append(r"         $w_\text{gps}=9.0$ fixed).}")
        lines.append(r"\label{tab:ablation_wmatch}")
        lines.append(r"\begin{tabular}{r rrrr r}")
        lines.append(r"\toprule")
        lines.append(r"$w_\text{match}$")
        lines.append(r"  & \parbox{0.9cm}{\centering Avg\\corr (m)}")
        lines.append(r"  & \parbox{0.9cm}{\centering Eval\\err (m)}")
        lines.append(r"  & \parbox{0.9cm}{\centering Res.\\before}")
        lines.append(r"  & \parbox{0.9cm}{\centering Res.\\after}")
        lines.append(r"  & \parbox{0.9cm}{\centering Seam\\SSIM} \\")
        lines.append(r"\midrule")
        for r in w_match_rows:
            lines.append(
                f"  {r['sweep_value']:.2f} & "
                f"{r['avg_correction_mag_m']:.3f} & "
                f"{r['avg_eval_pose_error_m']:.3f} & "
                f"{r['optimizer_mean_edge_before_m']:.2f} & "
                f"{r['optimizer_mean_edge_after_m']:.2f} & "
                f"{r['seam_ssim']:.4f} \\\\"
            )
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append(r"\end{table}")
        lines.append("")

    # --- Table: nfeatures sweep (ORB vs SIFT side by side) ---
    orb_nf = {int(s["sweep_value"]): s for s in summaries if s["sweep"] == "nfeatures"}
    sift_nf = {int(s["sweep_value"]): s for s in summaries if s["sweep"] == "nfeatures_sift"}
    nf_vals = sorted(set(orb_nf.keys()) | set(sift_nf.keys()))
    if nf_vals:
        lines.append(r"% Feature count sensitivity (data1, clean)")
        lines.append(r"\begin{table}[t]")
        lines.append(r"\centering")
        lines.append(r"\caption{Effect of feature count on optimizer runtime and quality")
        lines.append(r"         (data1, clean trajectory).  ORB and SIFT are compared at")
        lines.append(r"         matched feature budgets.}")
        lines.append(r"\label{tab:ablation_nfeatures}")
        lines.append(r"\begin{tabular}{r rr rr rr}")
        lines.append(r"\toprule")
        lines.append(r" & \multicolumn{2}{c}{Opt.\ time (ms)}")
        lines.append(r" & \multicolumn{2}{c}{Edges}")
        lines.append(r" & \multicolumn{2}{c}{Seam SSIM} \\")
        lines.append(r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}")
        lines.append(r"Features & ORB & SIFT & ORB & SIFT & ORB & SIFT \\")
        lines.append(r"\midrule")
        for nf in nf_vals:
            orb = orb_nf.get(nf)
            sift = sift_nf.get(nf)
            o_opt = f"{orb['avg_optimization_ms']:.0f}" if orb else "---"
            s_opt = f"{sift['avg_optimization_ms']:.0f}" if sift else "---"
            o_edges = f"{orb['n_edges']}" if orb else "---"
            s_edges = f"{sift['n_edges']}" if sift else "---"
            o_ssim = f"{orb['seam_ssim']:.4f}" if orb else "---"
            s_ssim = f"{sift['seam_ssim']:.4f}" if sift else "---"
            lines.append(f"  {nf} & {o_opt} & {s_opt} & {o_edges} & {s_edges} & {o_ssim} & {s_ssim} \\\\")
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append(r"\end{table}")
        lines.append("")

    # --- Table: solve_every sweep ---
    solve_rows = [s for s in summaries if s["sweep"] == "solve_every"]
    if solve_rows:
        lines.append(r"% Solve interval sensitivity (data1, clean, ORB)")
        lines.append(r"\begin{table}[t]")
        lines.append(r"\centering")
        lines.append(r"\caption{Effect of solve interval on runtime and correction")
        lines.append(r"         (data1, clean trajectory, ORB detector).}")
        lines.append(r"\label{tab:ablation_solve}")
        lines.append(r"\begin{tabular}{r rrrr}")
        lines.append(r"\toprule")
        lines.append(r"Solve interval")
        lines.append(r"  & \parbox{1.0cm}{\centering Avg opt\\(ms)}")
        lines.append(r"  & \parbox{1.0cm}{\centering Avg total\\(ms)}")
        lines.append(r"  & Edges")
        lines.append(r"  & \parbox{0.9cm}{\centering Seam\\SSIM} \\")
        lines.append(r"\midrule")
        for r in solve_rows:
            lines.append(
                f"  {int(r['sweep_value'])} & "
                f"{r['avg_optimization_ms']:.0f} & "
                f"{r['avg_total_ms']:.0f} & "
                f"{r['n_edges']} & "
                f"{r['seam_ssim']:.4f} \\\\"
            )
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append(r"\end{table}")
        lines.append("")

    tex = "\n".join(lines)
    tex_path = os.path.join(out_dir, "ablation_tables.tex")
    with open(tex_path, "w") as f:
        f.write(tex)
    print(f"  Ablation tables: {tex_path}")


if __name__ == "__main__":
    main()
