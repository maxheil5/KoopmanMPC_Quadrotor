import argparse
import subprocess
from pathlib import Path

import yaml


def run(cmd):
    print("[cmd]", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment_yaml", type=str, default="ubuntu scripts/config/experiment.yaml")
    ap.add_argument("--scenario", type=str, required=True)
    ap.add_argument("--mode", choices=["quantized"], default="quantized")
    args = ap.parse_args()

    exp_path = Path(args.experiment_yaml)
    if not exp_path.is_absolute():
        exp_path = (Path.cwd() / exp_path).resolve()
    exp = yaml.safe_load(exp_path.read_text())

    b_list = exp["quantization"]["b_list"]
    seeds = exp["quantization"]["seeds"]
    trials_per = int(exp["trials_per_setting"])

    run_trial = Path(__file__).resolve().parents[0] / "05_run_trial.py"

    for b in b_list:
        for seed in seeds:
            for k in range(1, trials_per + 1):
                cmd = [
                    "python3", str(run_trial),
                    "--experiment_yaml", str(exp_path),
                    "--scenario", args.scenario,
                    "--mode", "quantized",
                    "--b", str(b),
                    "--seed", str(seed),
                    "--trial_id", str(k),
                ]
                run(cmd)

    print("[06] Sweep complete.")


if __name__ == "__main__":
    main()
