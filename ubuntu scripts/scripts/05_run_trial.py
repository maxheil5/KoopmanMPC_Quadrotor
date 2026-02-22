import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

import argparse
import subprocess
import time

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

    # Standard run dir name
    tag = f"trial{args.trial_id:02d}"
    if args.mode == "quantized":
        tag = f"b{args.b}_seed{args.seed}_" + tag
    run_dir = ensure_dir(out_root / args.scenario / f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}")

    # Snapshot configs
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

    # 1) Run logger INTO run_dir
    if args.mode == "raw":
        script = root / "scripts" / "01_log_state_mavlink.py"
        cmd = ["python3", str(script),
               "--experiment_yaml", str(exp_path),
               "--scenario", args.scenario,
               "--outdir", str(run_dir)]
        if args.duration_s > 0:
            cmd += ["--duration_s", str(args.duration_s)]
        run(cmd)
        state_csv_name = "state_raw.csv"
    else:
        script = root / "scripts" / "02_log_state_quantized_mavlink.py"
        cmd = ["python3", str(script),
               "--experiment_yaml", str(exp_path),
               "--scenario", args.scenario,
               "--b", str(args.b),
               "--seed", str(args.seed),
               "--outdir", str(run_dir)]
        if args.duration_s > 0:
            cmd += ["--duration_s", str(args.duration_s)]
        run(cmd)
        state_csv_name = "state_raw_and_qd.csv"

    state_csv_path = run_dir / state_csv_name
    if not state_csv_path.exists():
        raise FileNotFoundError(f"Expected state CSV not found: {state_csv_path}")

    # 2) Extract inputs from newest ULog into run_dir
    script03 = root / "scripts" / "03_log_inputs_from_ulog.py"
    run(["python3", str(script03), "--outdir", str(run_dir)])

    # 3) Export aligned table for MATLAB
    script04 = root / "scripts" / "04_export_csv_to_matlab.py"
    run(["python3", str(script04), "--run_dir", str(run_dir), "--state_csv", state_csv_name])

    manifest["outputs"] = {
        "state_csv": str(state_csv_path),
        "inputs_csv": str(run_dir / "inputs.csv"),
        "inputs_meta_json": str(run_dir / "inputs_meta.json"),
        "trial_for_matlab_csv": str(run_dir / "trial_for_matlab.csv"),
        "trial_meta_json": str(run_dir / "trial_for_matlab_meta.json"),
        "logger_manifest_json": str(run_dir / "logger_manifest.json"),
    }

    write_json(run_dir / exp["paths"]["run_manifest_name"], manifest)
    print(f"[05] Trial done. Manifest: {run_dir / exp['paths']['run_manifest_name']}")


if __name__ == "__main__":
    main()
