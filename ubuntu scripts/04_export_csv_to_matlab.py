import argparse
from pathlib import Path
import json

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run_dir", type=str, required=True, help="Folder containing state_*.csv and inputs.csv")
    ap.add_argument("--state_csv", type=str, default="", help="Optional override state csv filename")
    ap.add_argument("--inputs_csv", type=str, default="inputs.csv")
    ap.add_argument("--out_csv", type=str, default="trial_for_matlab.csv")
    ap.add_argument("--out_meta", type=str, default="trial_for_matlab_meta.json")
    ap.add_argument("--max_dt_s", type=float, default=0.02, help="max time mismatch when aligning inputs to state")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        raise FileNotFoundError(run_dir)

    # Choose state CSV
    if args.state_csv:
        state_path = run_dir / args.state_csv
    else:
        # prefer quantized file if present
        cand = [run_dir / "state_raw_and_qd.csv", run_dir / "state_raw.csv"]
        state_path = next((p for p in cand if p.exists()), None)
        if state_path is None:
            raise FileNotFoundError("No state_raw_and_qd.csv or state_raw.csv in run_dir")

    inputs_path = run_dir / args.inputs_csv
    if not inputs_path.exists():
        raise FileNotFoundError(f"Missing inputs.csv in run_dir: {inputs_path}")

    df_x = pd.read_csv(state_path)
    df_u = pd.read_csv(inputs_path)

    # Build time axes
    # state: use t_wall_s if present, else derive from lp_time_boot_ms
    if "t_wall_s" in df_x.columns:
        df_x["t_s"] = pd.to_numeric(df_x["t_wall_s"], errors="coerce")
    elif "lp_time_boot_ms" in df_x.columns:
        t0 = df_x["lp_time_boot_ms"].iloc[0]
        df_x["t_s"] = (pd.to_numeric(df_x["lp_time_boot_ms"], errors="coerce") - t0) * 1e-3
    else:
        raise ValueError("State CSV has no usable time column")

    if "t_s" not in df_u.columns:
        raise ValueError("inputs.csv must contain t_s (it should, from 03 extractor)")

    df_x = df_x.dropna(subset=["t_s"]).sort_values("t_s").reset_index(drop=True)
    df_u = df_u.dropna(subset=["t_s"]).sort_values("t_s").reset_index(drop=True)

    # Align inputs to state times (nearest neighbor within max_dt_s)
    aligned = pd.merge_asof(
        df_x,
        df_u,
        on="t_s",
        direction="nearest",
        tolerance=args.max_dt_s,
        suffixes=("", "_u"),
    )

    out_csv = run_dir / args.out_csv
    out_meta = run_dir / args.out_meta

    aligned.to_csv(out_csv, index=False)

    meta = {
        "run_dir": str(run_dir),
        "state_csv": str(state_path),
        "inputs_csv": str(inputs_path),
        "out_csv": str(out_csv),
        "rows_state": int(len(df_x)),
        "rows_inputs": int(len(df_u)),
        "rows_aligned": int(len(aligned)),
        "max_dt_s": args.max_dt_s,
        "note": "This is a MATLAB-friendly flat table. Next step: export .mat struct in the exact format your MATLAB pipeline expects.",
    }
    out_meta.write_text(json.dumps(meta, indent=2, sort_keys=True))

    print(f"[04] Wrote: {out_csv}")
    print(f"[04] Wrote: {out_meta}")


if __name__ == "__main__":
    main()
