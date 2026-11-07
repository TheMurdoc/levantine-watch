"""Run: python collector/tests/test_ais_boxes.py   (no pytest needed)"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402

os.environ.pop("AIS_CORRIDOR", None)
assert len(collect.ais_boxes()) == 2
assert collect.in_ais_area(35.35, 25.9)        # south of Crete, inside the corridor
assert collect.in_ais_area(34.16, 30.07)       # last published GSI waypoint
assert collect.in_ais_area(34.7, 33.0)         # Cyprus, main box
assert not collect.in_ais_area(38.5, 27.0)     # Aegean, outside both
assert not collect.in_ais_area(None, 25.0)
os.environ["AIS_CORRIDOR"] = "0"
assert len(collect.ais_boxes()) == 1 and not collect.in_ais_area(35.35, 25.9)
print("ais boxes ok")
