import argparse
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
from pyulog import ULog


def _candidate_log_dirs() -> List[Path]:
    home = Path.home()
    return [
        home / "src" / "PX4-Autopilot" / "build" / "px4_sitl_default" / "rootfs" / "log",
        home / "src" / "PX4-Autopilot" / "build" / "px4_sitl_default" / "log",
        Path.cwd() / "log",
    ]


def find_latest_ulg(search_dir: Optional[Path] = None) -> Path:
    dirs = [search_dir] if search_dir else _candidate_log_dirs()
    ulgs: List[Path] = []
    for d in dirs:
        if d and d.exists():
            ulgs += list(d.rglob("*.ulg"))
    if not ulgs:
        raise FileNotFoundError(
            "No .ulg files found. Pass --ulg <path> or --search_dir <dir>."
        )
    return max(ulgs, key=lambda p: p.stat().st_mtime)


def find_latest_ulg_in_window(search_dir: Optional[Path], start_epoch_s: float, end_epoch_s: float) -> Path:
    """
    Robust selection: choose the newest .ulg whose modification time falls within [start, end].
    If none, fall back to newest overall and record that decision in meta.
    """
    dirs = [search_dir] if search_dir else _candidate_log_dirs()
    candidates: List[Path] = []
    for d in dirs:
        if d and d.exists():
            for p in d.rglob("*.ulg"):
                mt = p.stat().st_mtime
                if start_epoch_s <= mt <= end_epoch_s:
                    candidates.append(p)

    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)

    # Fallback
    return find_latest_ulg(search_dir)


def get_dataset(ulog: ULog, name: str):
    for d in ulog.data_list:
        if d.name == name:
            return d
    return None


def col_any(data: Dict[str, Any], *names: str) -> Optional[str]:
    for n in names:
        if n in data:
            return n
    return None


def extract_inputs(ulog: ULog) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "selected_proxy": None,
        "notes": [],
        "available_topics": sorted(set(d.name for d in ulog.data_list)),
    }

    ds_thrust = get_dataset(ulog, "vehicle_thrust_setpoint")
    ds_torque = get_dataset(ulog, "vehicle_torque_setpoint")
    ds_rates_sp = get_dataset(ulog, "vehicle_rates_setpoint")
    ds_act0 = get_dataset(ulog, "actuator_controls_0")

    def df_from(ds, cols: Dict[str, str]) -> pd.DataFrame:
        data = ds.data
        ts_key = col_any(data, "timestamp", "timestamp_sample")
        if ts_key is None:
            raise KeyError(f"{ds.name}: no timestamp field found")
        out = {"timestamp_us": data[ts_key].astype("int64")}
        for out_name, in_key in cols.items():
            out[out_name] = data[in_key]
        df = pd.DataFrame(out).sort_values("timestamp_us").reset_index(drop=True)
        df["t_s"] = (df["timestamp_us"] - df["timestamp_us"].iloc[0]) * 1e-6
        return df

    # Proxy 1: thrust + torque setpoints
    if ds_thrust is not None and ds_torque is not None:
        td = ds_thrust.data
        qd = ds_torque.data

        thr_z = col_any(td, "xyz[2]", "thrust_body[2]", "thrust[2]", "thrust_z")
        tau_x = col_any(qd, "xyz[0]", "torque[0]", "torque_body[0]")
        tau_y = col_any(qd, "xyz[1]", "torque[1]", "torque_body[1]")
        tau_z = col_any(qd, "xyz[2]", "torque[2]", "torque_body[2]")

        if thr_z and tau_x and tau_y and tau_z:
            dfT = df_from(ds_thrust, {"T_proxy": thr_z})
            dfM = df_from(ds_torque, {"tau_x": tau_x, "tau_y": tau_y, "tau_z": tau_z})

            df = pd.merge_asof(
                dfT.sort_values("timestamp_us"),
                dfM.sort_values("timestamp_us"),
                on="timestamp_us",
                direction="nearest",
                tolerance=20000,
            ).dropna()

            meta["selected_proxy"] = "thrust+torque_setpoints"
            meta["mapping"] = {
                "u": ["T_proxy", "tau_x", "tau_y", "tau_z"],
                "topics": ["vehicle_thrust_setpoint", "vehicle_torque_setpoint"],
                "fields": {"T_proxy": thr_z, "tau_*": [tau_x, tau_y, tau_z]},
                "note": "T_proxy uses thrust vector Z component; sign conventions depend on PX4 body frame.",
            }
            return df, meta

        meta["notes"].append("Found thrust/torque setpoint topics but required fields not found.")

    # Proxy 2: thrust setpoint + rates setpoint
    if ds_thrust is not None and ds_rates_sp is not None:
        td = ds_thrust.data
        rd = ds_rates_sp.data

        thr_z = col_any(td, "xyz[2]", "thrust_body[2]", "thrust[2]", "thrust_z")
        psp = col_any(rd, "roll", "roll_rate", "rollspeed")
        qsp = col_any(rd, "pitch", "pitch_rate", "pitchspeed")
        rsp = col_any(rd, "yaw", "yaw_rate", "yawspeed")

        if thr_z and psp and qsp and rsp:
            dfT = df_from(ds_thrust, {"T_proxy": thr_z})
            dfR = df_from(ds_rates_sp, {"p_sp": psp, "q_sp": qsp, "r_sp": rsp})

            df = pd.merge_asof(
                dfT.sort_values("timestamp_us"),
                dfR.sort_values("timestamp_us"),
                on="timestamp_us",
                direction="nearest",
                tolerance=20000,
            ).dropna()

            meta["selected_proxy"] = "thrust_setpoint+rates_setpoint"
            meta["mapping"] = {
                "u": ["T_proxy", "p_sp", "q_sp", "r_sp"],
                "topics": ["vehicle_thrust_setpoint", "vehicle_rates_setpoint"],
                "fields": {"T_proxy": thr_z, "p_sp": psp, "q_sp": qsp, "r_sp": rsp},
                "note": "Rates setpoints are body rate commands; thrust uses thrust vector Z component.",
            }
            return df, meta

        meta["notes"].append("Found thrust+rates setpoint topics but required fields not found.")

    # Proxy 3: actuator_controls_0
    if ds_act0 is not None:
        ad = ds_act0.data
        c0 = col_any(ad, "control[0]")
        c1 = col_any(ad, "control[1]")
        c2 = col_any(ad, "control[2]")
        c3 = col_any(ad, "control[3]")
        if c0 and c1 and c2 and c3:
            df = df_from(ds_act0, {"u0": c0, "u1": c1, "u2": c2, "u3": c3})
            meta["selected_proxy"] = "actuator_controls_0"
            meta["mapping"] = {
                "u": ["u0", "u1", "u2", "u3"],
                "topics": ["actuator_controls_0"],
                "fields": {"u0..u3": [c0, c1, c2, c3]},
                "note": "Actuator controls are normalized; mapping to thrust/moments requires mixer model.",
            }
            return df, meta

        meta["notes"].append("Found actuator_controls_0 but control[0..3] not found.")

    raise RuntimeError(
        "Could not extract any input proxy. Inspect available topics in inputs_meta.json and extend extractor."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ulg", type=str, default="", help="Path to .ulg (optional). If empty, auto-select.")
    ap.add_argument("--search_dir", type=str, default="", help="Directory to search for .ulg (optional).")
    ap.add_argument("--outdir", type=str, default=".", help="Output directory (default: current).")
    ap.add_argument("--out_csv", type=str, default="inputs.csv", help="CSV filename.")
    ap.add_argument("--out_meta", type=str, default="inputs_meta.json", help="Meta filename.")
    ap.add_argument("--start_epoch_s", type=float, default=0.0, help="Trial start epoch seconds (optional).")
    ap.add_argument("--end_epoch_s", type=float, default=0.0, help="Trial end epoch seconds (optional).")
    args = ap.parse_args()

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    search_dir = Path(args.search_dir).expanduser().resolve() if args.search_dir else None

    # Choose ULog
    ulg_path: Path
    if args.ulg:
        ulg_path = Path(args.ulg).expanduser().resolve()
    elif args.start_epoch_s > 0 and args.end_epoch_s > 0:
        ulg_path = find_latest_ulg_in_window(search_dir, args.start_epoch_s, args.end_epoch_s)
    else:
        ulg_path = find_latest_ulg(search_dir)

    print(f"[03] Using ULog: {ulg_path}")
    ulog = ULog(str(ulg_path))

    df, meta = extract_inputs(ulog)

    csv_path = outdir / args.out_csv
    meta_path = outdir / args.out_meta

    df.to_csv(csv_path, index=False)

    meta["ulg_path"] = str(ulg_path)
    meta["selection"] = {
        "used_window": bool(args.start_epoch_s > 0 and args.end_epoch_s > 0),
        "start_epoch_s": args.start_epoch_s,
        "end_epoch_s": args.end_epoch_s,
        "search_dir": str(search_dir) if search_dir else None,
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))

    print(f"[03] Wrote: {csv_path}")
    print(f"[03] Wrote: {meta_path}")
    print(f"[03] Selected proxy: {meta.get('selected_proxy')}")


if __name__ == "__main__":
    main()
