import argparse
import json
from pathlib import Path

import pandas as pd
import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment_yaml", type=str, default="ubuntu scripts/config/experiment.yaml")
    ap.add_argument("--scenario", type=str, required=True)
    args = ap.parse_args()

    exp_path = Path(args.experiment_yaml)
    if not exp_path.is_absolute():
        exp_path = (Path.cwd() / exp_path).resolve()
    exp = yaml.safe_load(exp_path.read_text())

    out_root = (Path.cwd() / exp["paths"]["out_root"]).resolve()
    scenario_dir = out_root / args.scenario
    bounds_yaml = exp["quantization"]["bounds_yaml"]
    bounds_path = (Path.cwd() / bounds_yaml).resolve()
    bounds_cfg = yaml.safe_load(bounds_path.read_text())
    vars_ = list(bounds_cfg["bounds"].keys())

    rows = []

    # Find all quantized CSVs under scenario
    for csv_path in scenario_dir.rglob("state_raw_and_qd.csv"):
        run_dir = csv_path.parent
        # parse b, seed from folder name if present
        name = run_dir.name
        b = None
        seed = None
        if name.startswith("b") and "_seed" in name:
            try:
                b = int(name.split("_")[0][1:])
                seed = int(name.split("_seed")[1].split("_")[0])
            except Exception:
                pass

        df = pd.read_csv(csv_path)

        # Compute RMSE for each variable between raw and qd
        metrics = {"run_dir": str(run_dir), "b": b, "seed": seed}
        for k in vars_:
            if k in df.columns and f"{k}_qd" in df.columns:
                a = pd.to_numeric(df[k], errors="coerce")
                q = pd.to_numeric(df[f"{k}_qd"], errors="coerce")
                e = (a - q)
                rmse = (e.pow(2).mean()) ** 0.5
                metrics[f"rmse_{k}"] = float(rmse)
        rows.append(metrics)

        # write per-run metrics
        (run_dir / "metrics_raw_vs_qd.json").write_text(json.dumps(metrics, indent=2, sort_keys=True))

    if not rows:
        print(f"No state_raw_and_qd.csv found under {scenario_dir}")
        return

    summary = pd.DataFrame(rows)
    summary_path = scenario_dir / "metrics_summary_raw_vs_qd.csv"
    summary.to_csv(summary_path, index=False)
    print("Wrote:", summary_path)


if __name__ == "__main__":
    main()
