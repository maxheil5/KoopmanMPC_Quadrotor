import socket
import sys
from pathlib import Path

import yaml
from pymavlink import mavutil


def ok(msg): print(f"✅ {msg}", flush=True)
def bad(msg): print(f"❌ {msg}", flush=True)


def udp_port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    root = Path(__file__).resolve().parents[1]  # ubuntu scripts/
    cfg_path = root / "config" / "experiment.yaml"

    print(f"Root: {root}")
    print(f"Config: {cfg_path}")

    # 1) Load config
    if not cfg_path.exists():
        bad("experiment.yaml not found")
        sys.exit(1)

    cfg = yaml.safe_load(cfg_path.read_text())
    ok("Loaded experiment.yaml")

    port = int(cfg["mavlink"]["listen_port"])
    out_root = Path(cfg["paths"]["out_root"])

    # 2) Output directory
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        testfile = out_root / ".write_test"
        testfile.write_text("ok")
        testfile.unlink()
        ok(f"Outputs folder writable: {out_root}")
    except Exception as e:
        bad(f"Outputs folder not writable: {out_root} ({e})")
        sys.exit(1)

    # 3) UDP bind check
    if udp_port_open(port):
        ok(f"UDP port {port} is bindable (no obvious conflict)")
    else:
        bad(f"UDP port {port} not bindable (something is already bound)")
        print("This is NOT always fatal (PX4 may already be bound). Proceeding to heartbeat test...")

    # 4) Heartbeat check
    print(f"Waiting for PX4 heartbeat on udpin:{port} ...")
    try:
        m = mavutil.mavlink_connection(f"udpin:0.0.0.0:{port}", dialect="common")
        m.wait_heartbeat(timeout=10)
        ok(f"Heartbeat received (sys={m.target_system}, comp={m.target_component})")
    except Exception as e:
        bad(f"No heartbeat on port {port} within timeout ({e})")
        print("Fix: Start PX4 SITL and confirm it prints 'remote port 14550' in the console.")
        sys.exit(1)

    ok("ENV CHECK PASSED")


if __name__ == "__main__":
    main()
