import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment_yaml", type=str, default="ubuntu scripts/config/experiment.yaml")
    ap.add_argument("--scenario", type=str, required=True)
    ap.add_argument("--metric_prefix", type=str, default="rmse_", help="columns to plot start with this prefix")
    args = ap.parse_args()

    exp_path = Path(args.experiment_yaml)
    if not exp_path.is_absolute():
        exp_path = (Path.cwd() / exp_path).resolve()
    exp = yaml.safe_load(exp_path.read_text())

    out_root = (Path.cwd() / exp["paths"]["out_root"]).resolve()
    scenario_dir = out_root / args.scenario
    summary_path = scenario_dir / "metrics_summary_raw_vs_qd.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Run 07 first. Missing: {summary_path}")

    df = pd.read_csv(summary_path)
    fig_dir = scenario_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Identify metric columns
    metric_cols = [c for c in df.columns if c.startswith(args.metric_prefix)]
    if "b" not in df.columns:
        raise ValueError("metrics file missing 'b' column")

    # Plot each metric vs b (mean over seeds/trials)
    for col in metric_cols:
        g = df.groupby("b")[col].mean().reset_index()
        plt.figure()
        plt.plot(g["b"], g[col], marker="o")
        plt.xlabel("bit-width b")
        plt.ylabel(col)
        plt.title(f"{args.scenario}: {col} vs b")
        out = fig_dir / f"{col}_vs_b.png"
        plt.savefig(out, dpi=200, bbox_inches="tight")
        plt.close()
        print("Wrote:", out)


if __name__ == "__main__":
    main()
