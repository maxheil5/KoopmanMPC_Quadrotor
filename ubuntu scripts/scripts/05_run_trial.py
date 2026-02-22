import argparse
import subprocess
from pathlib import Path

import yaml
from common.io_utils import ensure_dir, write_json


def run(cmd, cwd=None):
    print("[cmd]", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment_yaml", type=str, default="ubuntu scripts/config/experiment.yaml")
    ap.add_argument("--scenario", type=str, required=True)
    ap.add_argument("--mode", choices=["raw", "quantized"], default="quantized")
    ap.add_argument("--b", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--trial_id", type=int, default=1)
    ap.add_argument("--duration_s", type=float, default=0.0)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]  # ubuntu scripts/
    exp_path = Path(args.experiment_yaml)
    if not exp_path.is_absolute():
        exp_path = (Path.cwd() / exp_path).resolve()
    exp = yaml.safe_load(exp_path.read_text())

    out_root = (Path.cwd() / exp["paths"]["out_root"]).resolve()
    ensure_dir(out_root)

    # Make a standardized run directory
    tag = f"trial{args.trial_id:02d}"
    if args.mode == "quantized":
        tag = f"b{args.b}_seed{args.seed}_" + tag

    run_dir = ensure_dir(out_root / args.scenario / tag)

    # Copy config snapshots into run_dir for reproducibility
    cfg_snapshot_dir = ensure_dir(run_dir / "config_snapshot")
    (cfg_snapshot_dir / "experiment.yaml").write_text(exp_path.read_text())
    (cfg_snapshot_dir / "ref_traj.yaml").write_text((root / "config" / "ref_traj.yaml").read_text())
    bounds_yaml = exp["quantization"]["bounds_yaml"]
    (cfg_snapshot_dir / "quantization_bounds.yaml").write_text((Path.cwd() / bounds_yaml).read_text())

    manifest = {
        "scenario": args.scenario,
        "mode": args.mode,
        "b": args.b if args.mode == "quantized" else None,
        "seed": args.seed if args.mode == "quantized" else None,
        "trial_id": args.trial_id,
        "run_dir": str(run_dir),
    }

    # Decide which logger to run
    if args.mode == "raw":
        script = root / "scripts" / "01_log_state_mavlink.py"
        cmd = ["python3", str(script), "--scenario", args.scenario]
        if args.duration_s > 0:
            cmd += ["--duration_s", str(args.duration_s)]
        run(cmd)
        manifest["outputs"] = {"state_raw_csv": "state_raw.csv (inside timestamped subdir per 01 script)"}
    else:
        script = root / "scripts" / "02_log_state_quantized_mavlink.py"
        cmd = ["python3", str(script), "--scenario", args.scenario, "--b", str(args.b), "--seed", str(args.seed)]
        if args.duration_s > 0:
            cmd += ["--duration_s", str(args.duration_s)]
        # Run quantized logger; it will create its own timestamped folder inside scenario/
        run(cmd)
        manifest["outputs"] = {"state_raw_and_qd_csv": "state_raw_and_qd.csv (inside timestamped subdir per 02 script)"}

    write_json(run_dir / exp["paths"]["run_manifest_name"], manifest)
    print(f"[05] Trial done. Manifest: {run_dir / exp['paths']['run_manifest_name']}")


if __name__ == "__main__":
    main()
