"""U.2: the screenshot and clutter-count harness."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _harness():
    spec = importlib.util.spec_from_file_location("screen_harness", ROOT / "scripts" / "screen_harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_draws_the_three_screens_the_brief_names(tmp_path):
    h = _harness()
    results = h.run(["suggestions", "companion", "style"], tmp_path, sizes=[(1440, 900, 1.0)])
    report = results["1440x900"]
    assert report["screen"]["available"] == [1440, 900]
    for name in ("suggestions", "companion", "style"):
        assert "error" not in report["screens"][name], report["screens"][name]
        assert (tmp_path / f"{name}_1440x900.png").stat().st_size > 1000
    # Counts were taken at the baseline size and match it.
    baseline = json.loads(h.BASELINE.read_text())
    assert h.compare_counts(report["counts"], baseline) == []
    assert report["counts"]["screens"]["companion"]["sections"] == 7


def test_a_rise_above_the_baseline_is_reported():
    h = _harness()
    base = {"screens": {"companion": {"buttons": 18, "menu_items": 0, "sections": 7, "inner_tabs": 0}},
            "right_click": {"text_selection": 22}}
    now = {"screens": {"companion": {"buttons": 19, "menu_items": 0, "sections": 6, "inner_tabs": 0}},
           "right_click": {"text_selection": 22}}
    assert h.compare_counts(now, base) == ["companion: buttons 18 → 19"]


def test_image_comparison(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QColor, QImage
    h = _harness()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    for folder, colour in ((a, "white"), (b, "white")):
        img = QImage(20, 10, QImage.Format.Format_RGB32)
        img.fill(QColor(colour))
        img.save(str(folder / "same.png"))
    img.fill(QColor("black"))
    img.save(str(b / "changed.png"))
    img.fill(QColor("white"))
    img.save(str(a / "changed.png"))
    same, different = h.compare_images(a, b)
    assert same == ["same.png"] and different == ["changed.png"]


def test_every_baseline_screen_can_be_drawn():
    h = _harness()
    baseline = json.loads(h.BASELINE.read_text())
    assert set(baseline["screens"]) <= set(h.SCREENS)
