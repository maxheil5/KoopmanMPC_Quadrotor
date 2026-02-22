import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))  # allow `common.*` imports reliably

import argparse
import csv
import time

import yaml

from common.mavlink_conn import connect_udpin
from common.io_utils import ensure_dir, write_json
from common.quantize import QuantConfig, dither_quantize_decode, inflate_bounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment_yaml", type=str, default="ubuntu scripts/config/experiment.yaml")
    ap.add_argument("--scenario", type=str, required=True)
    ap.add_argument("--b", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--outdir", type=str, default="", help="If set, write outputs directly here (no extra timestamp folder).")
    ap.add_argument("--duration_s", type=float, default=0.0)
    ap.add_argument("--rate_hz", type=float, default=0.0)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]  # ubuntu scripts/
    exp_path = Path(args.experiment_yaml)
    if not exp_path.is_absolute():
        exp_path = (Path.cwd() / exp_path).resolve()

    exp = yaml.safe_load(exp_path.read_text())
    ref = yaml.safe_load((root / "config" / "ref_traj.yaml").read_text())

    bounds_path = Path(exp["quantization"]["bounds_yaml"])
    if not bounds_path.is_absolute():
        bounds_path = (Path.cwd() / bounds_path).resolve()
    bounds_cfg = yaml.safe_load(bounds_path.read_text())
    bounds = bounds_cfg["bounds"]

    port = int(exp["mavlink"]["listen_port"])

    traj = ref["trajectories"][args.scenario]
    duration = float(args.duration_s) if args.duration_s > 0 else float(traj["duration_s"])
    rate_hz = float(args.rate_hz) if args.rate_hz > 0 else float(exp["logging"]["rate_hz"])
    dt = 1.0 / max(rate_hz, 1.0)

    margin = float(exp["quantization"].get("safety_margin_frac", 0.05))
    qc = QuantConfig(b=int(args.b), seed=int(args.seed), safety_margin_frac=margin)

    # Decide output directory (robust mode uses --outdir)
    if args.outdir:
        run_dir = ensure_dir(Path(args.outdir).expanduser().resolve())
        manifest_name = "logger_manifest.json"  # avoid clobbering trial manifest
    else:
        out_root = (Path.cwd() / exp["paths"]["out_root"]).resolve()
        ensure_dir(out_root)
        run_dir = ensure_dir(out_root / args.scenario / f"b{qc.b}_seed{qc.seed}_{time.strftime('%Y%m%d_%H%M%S')}")
        manifest_name = exp["paths"]["run_manifest_name"]

    csv_path = run_dir / "state_raw_and_qd.csv"
    manifest_path = run_dir / manifest_name

    print(f"[02] Connecting MAVLink udpin:{port} ...")
    m = connect_udpin(port=port, timeout_s=15.0)
    print(f"[02] Heartbeat OK (sys={m.target_system}, comp={m.target_component})")
    print(f"[02] Logging {duration:.1f}s at ~{rate_hz:.1f} Hz, b={qc.b}, seed={qc.seed} -> {csv_path}")

    base_fields = [
        "t_wall_s",
        "lp_time_boot_ms","x_n","y_e","z_d","vx","vy","vz",
        "att_time_boot_ms","roll","pitch","yaw","p","q","r",
        "q_time_boot_ms","q1","q2","q3","q4",
    ]
    qd_vars = list(bounds.keys())
    fields = base_fields + [f"{k}_qd" for k in qd_vars]

    row = {k: "" for k in fields}
    t0 = time.time()
    last_write = 0.0
    row_counter = 0

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()

        while True:
            t = time.time() - t0
            if t >= duration:
                break

            msg = m.recv_match(blocking=True, timeout=1.0)
            if msg is None:
                continue
            mtype = msg.get_type()

            if mtype == "LOCAL_POSITION_NED":
                row["t_wall_s"] = f"{t:.6f}"
                row["lp_time_boot_ms"] = getattr(msg, "time_boot_ms", "")
                row["x_n"] = float(getattr(msg, "x", 0.0))
                row["y_e"] = float(getattr(msg, "y", 0.0))
                row["z_d"] = float(getattr(msg, "z", 0.0))
                row["vx"]  = float(getattr(msg, "vx", 0.0))
                row["vy"]  = float(getattr(msg, "vy", 0.0))
                row["vz"]  = float(getattr(msg, "vz", 0.0))

            elif mtype == "ATTITUDE":
                row["t_wall_s"] = f"{t:.6f}"
                row["att_time_boot_ms"] = getattr(msg, "time_boot_ms", "")
                row["roll"]  = float(getattr(msg, "roll", 0.0))
                row["pitch"] = float(getattr(msg, "pitch", 0.0))
                row["yaw"]   = float(getattr(msg, "yaw", 0.0))
                row["p"] = float(getattr(msg, "rollspeed", 0.0))
                row["q"] = float(getattr(msg, "pitchspeed", 0.0))
                row["r"] = float(getattr(msg, "yawspeed", 0.0))

            elif mtype == "ATTITUDE_QUATERNION":
                row["t_wall_s"] = f"{t:.6f}"
                row["q_time_boot_ms"] = getattr(msg, "time_boot_ms", "")
                row["q1"] = float(getattr(msg, "q1", 0.0))
                row["q2"] = float(getattr(msg, "q2", 0.0))
                row["q3"] = float(getattr(msg, "q3", 0.0))
                row["q4"] = float(getattr(msg, "q4", 0.0))

            have_pos = row["lp_time_boot_ms"] != ""
            have_att = (row["att_time_boot_ms"] != "") or (row["q_time_boot_ms"] != "")
            if (t - last_write) >= dt and have_pos and have_att:
                import random
                rng = random.Random(qc.seed + row_counter)  # deterministic per-row dither

                for k in qd_vars:
                    vmin, vmax = bounds[k]
                    vmin_i, vmax_i = inflate_bounds(float(vmin), float(vmax), qc.safety_margin_frac)
                    v = row.get(k, "")
                    if v == "" or v is None:
                        row[f"{k}_qd"] = ""
                    else:
                        row[f"{k}_qd"] = dither_quantize_decode(float(v), vmin_i, vmax_i, qc.b, rng)

                w.writerow(row)
                last_write = t
                row_counter += 1

    write_json(manifest_path, {
        "scenario": args.scenario,
        "duration_s": duration,
        "rate_hz": rate_hz,
        "mavlink_listen_port": port,
        "quantization": {
            "b": qc.b,
            "seed": qc.seed,
            "safety_margin_frac": qc.safety_margin_frac,
            "bounds_yaml": str(bounds_path),
        },
        "outputs": {"state_raw_and_qd_csv": str(csv_path)},
        "ref_traj": traj,
        "note": "Logger manifest. Trial-level manifest is written by 05_run_trial.py.",
    })

    print(f"[02] Done. Wrote {csv_path} and {manifest_path}")


if __name__ == "__main__":
    main()
