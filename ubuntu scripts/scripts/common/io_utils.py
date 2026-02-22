import json
import time
from pathlib import Path

def timestamp():
    return time.strftime("%Y%m%d_%H%M%S")

def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def write_json(path: Path, obj: dict):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True))

def make_run_dir(out_root: Path, scenario: str, tag: str = "") -> Path:
    """
    Standard run directory:
      <out_root>/<scenario>/<YYYYmmdd_HHMMSS>[_tag]/
    """
    name = timestamp()
    if tag:
        name = f"{name}_{tag}"
    run_dir = out_root / scenario / name
    ensure_dir(run_dir)
    return run_dir
