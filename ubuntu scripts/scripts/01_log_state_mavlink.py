import argparse
import csv
import time
from pathlib import Path

import yaml
from common.mavlink_conn import connect_udpin
from common.io_utils import ensure_dir, write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment_yaml", type=str, default="ubuntu scripts/config/experiment.yaml")
    ap.add_argument("--scenario", type=str, required=True, help="hover or excitation (must exist in ref_traj.yaml)")
    ap.add_argument("--duration_s", type=float, default=0.0, help="override duration; 0 uses ref_traj.yaml")
    ap.add_argument("--rate_hz", type=float, default=0.0, help="override rate; 0 uses experiment.yaml logging.rate_hz")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]  # ubuntu scripts/
    exp_path = Path(args.experiment_yaml)
    if not exp_path.is_absolute():
        exp_path = (Path.cwd() / exp_path).resolve()

    ref_path = root / "config" / "ref_traj.yaml"

    exp = yaml.safe_load(exp_path.read_text())
    ref = yaml.safe_load(ref_path.read_text())

    port = int(exp["mavlink"]["listen_port"])
    out_root = (Path.cwd() / exp["paths"]["out_root"]).resolve()
    ensure_dir(out_root)

    traj = ref["trajectories"][args.scenario]
    duration = float(args.duration_s) if args.duration_s > 0 else float(traj["duration_s"])
    rate_hz = float(args.rate_hz) if args.rate_hz > 0 else float(exp["logging"]["rate_hz"])
    dt = 1.0 / max(rate_hz, 1.0)

    # Create run folder
    run_dir = ensure_dir(out_root / args.scenario / time.strftime("%Y%m%d_%H%M%S"))
    csv_path = run_dir / "state_raw.csv"
    manifest_path = run_dir / exp["paths"]["run_manifest_name"]

    # Connect MAVLink
    print(f"[01] Connecting MAVLink udpin:{port} ...")
    m = connect_udpin(port=port, timeout_s=15.0)
    print(f"[01] Heartbeat OK (sys={m.target_system}, comp={m.target_component})")
    print(f"[01] Logging {duration:.1f}s at ~{rate_hz:.1f} Hz -> {csv_path}")

    fields = [
        "t_wall_s",
        "lp_time_boot_ms","x_n","y_e","z_d","vx","vy","vz",
        "att_time_boot_ms","roll","pitch","yaw","p","q","r",
        "q_time_boot_ms","q1","q2","q3","q4",
    ]
    row = {k: "" for k in fields}
    t0 = time.time()
    last_write = 0.0

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
                row["x_n"] = getattr(msg, "x", "")
                row["y_e"] = getattr(msg, "y", "")
                row["z_d"] = getattr(msg, "z", "")
                row["vx"]  = getattr(msg, "vx", "")
                row["vy"]  = getattr(msg, "vy", "")
                row["vz"]  = getattr(msg, "vz", "")

            elif mtype == "ATTITUDE":
                row["t_wall_s"] = f"{t:.6f}"
                row["att_time_boot_ms"] = getattr(msg, "time_boot_ms", "")
                row["roll"]  = getattr(msg, "roll", "")
                row["pitch"] = getattr(msg, "pitch", "")
                row["yaw"]   = getattr(msg, "yaw", "")
                row["p"] = getattr(msg, "rollspeed", "")
                row["q"] = getattr(msg, "pitchspeed", "")
                row["r"] = getattr(msg, "yawspeed", "")

            elif mtype == "ATTITUDE_QUATERNION":
                row["t_wall_s"] = f"{t:.6f}"
                row["q_time_boot_ms"] = getattr(msg, "time_boot_ms", "")
                row["q1"] = getattr(msg, "q1", "")  # w
                row["q2"] = getattr(msg, "q2", "")  # x
                row["q3"] = getattr(msg, "q3", "")  # y
                row["q4"] = getattr(msg, "q4", "")  # z

            have_pos = row["lp_time_boot_ms"] != ""
            have_att = (row["att_time_boot_ms"] != "") or (row["q_time_boot_ms"] != "")
            if (t - last_write) >= dt and have_pos and have_att:
                w.writerow(row)
                last_write = t

    # Write manifest
    write_json(manifest_path, {
        "scenario": args.scenario,
        "duration_s": duration,
        "rate_hz": rate_hz,
        "mavlink_listen_port": port,
        "outputs": {
            "state_raw_csv": str(csv_path),
        },
        "ref_traj": traj,
    })

    print(f"[01] Done. Wrote {csv_path} and {manifest_path}")


if __name__ == "__main__":
    main()
