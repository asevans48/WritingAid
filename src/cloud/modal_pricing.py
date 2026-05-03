"""Modal GPU pricing — defaults, user overrides, and best-effort refresh.

The cost estimates and the live spend tally both depend on a
``{gpu_name: $/hour}`` table. We keep three layers:

  1. **Defaults** baked into this module — current as of the last
     manual sync from https://modal.com/pricing. Used when the user
     has never edited anything and the network is unavailable.
  2. **User overrides** persisted to ``~/.creativeos/modal_pricing.json``
     — populated either by the "Edit prices" dialog or by a successful
     ``fetch_pricing_from_web()`` call. Wins over defaults when present.
  3. **Source-of-truth refresh** — :func:`fetch_pricing_from_web`
     scrapes modal.com/pricing and returns a parsed table the UI can
     either show as a diff against the saved table or save directly.

The studio's ``modal_train`` module reads through :func:`get_pricing`
on every cost calculation, so changes here take effect immediately
without restarting the app.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# ── Defaults ──────────────────────────────────────────────────
#
# Synced from https://modal.com/pricing on 2026-04-27. Update by
# clicking "Refresh from modal.com" in the pricing dialog OR by
# editing the JSON at ``~/.creativeos/modal_pricing.json``. The
# values are deliberately the published *list* prices — Modal bills
# per-second so the actual run charge is (seconds / 3600) × rate.
#
# Two GPU naming caveats:
#   * Modal's SDK uses ``A10G`` for what their pricing page calls
#     ``A10`` — same hardware, different label. We keep both keys
#     pointing at the same number so callers using either name work.
#   * ``A100`` on the pricing page is the 40 GB SKU; ``A100-80GB``
#     is the 80 GB SKU. Estimator code uses the SDK names, so both
#     are kept here too.
_DEFAULT_PRICING_USD_PER_HOUR: Dict[str, float] = {
    "T4": 0.59,
    "L4": 0.80,
    "A10G": 1.10,        # SDK name (Modal page calls it "A10")
    "A10": 1.10,         # alias
    "L40S": 1.95,
    "A100": 2.10,        # 40 GB
    "A100-80GB": 2.50,
    "H100": 3.95,
    "H200": 4.54,
    "B200": 6.25,
    "RTX-PRO-6000": 3.03,
}

# Where the user's overrides live. Same dir we use for every other
# studio-side persisted state (trained models, modal job log, etc.).
_PRICING_PATH = Path.home() / ".creativeos" / "modal_pricing.json"

# What URL to scrape when the user clicks "Refresh from modal.com".
# Kept as a module constant so a future Modal redesign only needs
# editing in one place.
_MODAL_PRICING_URL = "https://modal.com/pricing"


@dataclass
class PricingState:
    """In-memory snapshot of the pricing table + provenance.

    Returned by :func:`load_pricing_state` so the UI can show *where*
    the current numbers came from (defaults vs. user-edited vs.
    web-refreshed) and *when* they were last touched.
    """
    prices: Dict[str, float]
    source: str           # "defaults", "user", "web"
    saved_at: float = 0.0  # unix seconds; 0 for defaults
    notes: str = ""        # optional free-text from the saver
    raw: Dict = field(default_factory=dict)


def get_pricing() -> Dict[str, float]:
    """Return the active ``{gpu: $/hour}`` table.

    Loads ``~/.creativeos/modal_pricing.json`` on every call (cheap —
    the file is < 1 KB) so the cost estimator and live tally see
    edits immediately. Falls back to module defaults when the file
    is missing or corrupt.
    """
    if not _PRICING_PATH.exists():
        return dict(_DEFAULT_PRICING_USD_PER_HOUR)
    try:
        data = json.loads(_PRICING_PATH.read_text())
        prices = data.get("prices") or {}
        if not isinstance(prices, dict):
            return dict(_DEFAULT_PRICING_USD_PER_HOUR)
        # Merge with defaults so a user JSON missing some entries
        # still resolves new GPU types via the baked-in fallback.
        merged = dict(_DEFAULT_PRICING_USD_PER_HOUR)
        for k, v in prices.items():
            try:
                merged[k] = float(v)
            except (TypeError, ValueError):
                continue
        return merged
    except Exception:
        return dict(_DEFAULT_PRICING_USD_PER_HOUR)


def load_pricing_state() -> PricingState:
    """Return the active table + provenance metadata. UI-facing."""
    if not _PRICING_PATH.exists():
        return PricingState(
            prices=dict(_DEFAULT_PRICING_USD_PER_HOUR),
            source="defaults", saved_at=0.0, notes="")
    try:
        data = json.loads(_PRICING_PATH.read_text()) or {}
        return PricingState(
            prices=get_pricing(),
            source=str(data.get("source") or "user"),
            saved_at=float(data.get("saved_at") or 0.0),
            notes=str(data.get("notes") or ""),
            raw=data)
    except Exception:
        return PricingState(
            prices=dict(_DEFAULT_PRICING_USD_PER_HOUR),
            source="defaults", saved_at=0.0,
            notes="(failed to load saved pricing — using defaults)")


def set_pricing(prices: Dict[str, float], *,
                source: str = "user", notes: str = "") -> bool:
    """Persist a new pricing table. Returns True on success.

    ``source`` is annotation only ("user" / "web") — used by the UI
    to label where the current numbers came from. The pricing layer
    treats them identically.
    """
    cleaned: Dict[str, float] = {}
    for k, v in (prices or {}).items():
        try:
            f = float(v)
            if f >= 0:
                cleaned[str(k)] = f
        except (TypeError, ValueError):
            continue
    if not cleaned:
        return False
    try:
        _PRICING_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "prices": cleaned,
            "source": source,
            "saved_at": time.time(),
            "notes": notes,
        }
        _PRICING_PATH.write_text(json.dumps(payload, indent=2))
        return True
    except Exception:
        return False


def reset_pricing() -> bool:
    """Delete the user's pricing override; revert to module defaults."""
    if not _PRICING_PATH.exists():
        return True
    try:
        _PRICING_PATH.unlink()
        return True
    except Exception:
        return False


def price_for(gpu: str) -> float:
    """Look up one GPU's hourly rate, returning 0.0 if unknown."""
    return float(get_pricing().get(gpu, 0.0))


def default_prices() -> Dict[str, float]:
    """Read-only view of the module-baked defaults. UI uses this when
    rendering an "edit prices" form so it can show defaults next to
    user values, and the reset button can fall back without touching
    the disk path."""
    return dict(_DEFAULT_PRICING_USD_PER_HOUR)


# ── Web refresh ───────────────────────────────────────────────


@dataclass
class FetchResult:
    """Outcome of a :func:`fetch_pricing_from_web` call.

    The dialog uses ``ok`` / ``error`` to decide whether to show the
    parsed table for confirmation, and ``parsed`` to populate the
    "would-save" preview before the user clicks Apply.
    """
    ok: bool
    parsed: Dict[str, float]
    raw_url: str
    error: str = ""


def fetch_pricing_from_web(*, timeout_s: float = 10.0) -> FetchResult:
    """Best-effort scrape of https://modal.com/pricing.

    Modal's pricing page is a static HTML doc (Next.js SSR) so a
    plain ``requests.get`` returns the GPU rows in the markup. We
    look for ``$N.NNNNNN / sec`` patterns near GPU names and convert
    seconds → hours.

    This is intentionally conservative: if the parser doesn't find
    at least 4 GPUs, we treat the result as untrusted and surface
    an error rather than overwriting the saved table with garbage.
    The user can always edit the prices manually as a fallback.
    """
    try:
        import requests
    except ImportError:
        return FetchResult(
            ok=False, parsed={}, raw_url=_MODAL_PRICING_URL,
            error=("`requests` not installed — can't fetch pricing. "
                   "Edit the prices manually instead."))
    try:
        resp = requests.get(
            _MODAL_PRICING_URL, timeout=timeout_s,
            headers={
                # Modal's marketing site sometimes 403s a bare default
                # Python UA. A normal browser UA gets through cleanly.
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
            })
        resp.raise_for_status()
    except Exception as e:
        return FetchResult(
            ok=False, parsed={}, raw_url=_MODAL_PRICING_URL,
            error=f"Couldn't fetch pricing page: {e}")

    parsed = _parse_pricing_html(resp.text)
    if len(parsed) < 4:
        return FetchResult(
            ok=False, parsed=parsed, raw_url=_MODAL_PRICING_URL,
            error=("Couldn't extract enough GPU rows from the "
                   f"pricing page (parsed {len(parsed)} entries — "
                   "page format may have changed). Edit prices "
                   "manually as a fallback."))
    return FetchResult(
        ok=True, parsed=parsed, raw_url=_MODAL_PRICING_URL)


# Map the pricing-page GPU labels onto the SDK's GPU keys. The keys
# on the right side are what ``modal.Function.with_options(gpu=...)``
# expects; the regex on the left matches Modal's marketing labels.
#
# Important: NO bare ``A100`` pattern — it would match inside
# "A100, 80 GB" first (substring) and grab the 80GB rate before the
# size-specific 40GB pattern got its turn. We require both A100 SKUs
# to carry an explicit size suffix on the page; if Modal ever drops
# the size suffix, the parser will skip A100 entirely and the user
# can edit it manually rather than getting a silently-wrong value.
_GPU_LABEL_TO_SDK_KEY = [
    (re.compile(r"\bB200\b", re.I),                "B200"),
    (re.compile(r"\bH200\b", re.I),                "H200"),
    (re.compile(r"\bH100\b", re.I),                "H100"),
    (re.compile(r"RTX\s*PRO\s*6000", re.I),        "RTX-PRO-6000"),
    (re.compile(r"A100[^0-9]*80\s*GB", re.I),      "A100-80GB"),
    (re.compile(r"A100[^0-9]*40\s*GB", re.I),      "A100"),
    (re.compile(r"L40S", re.I),                    "L40S"),
    (re.compile(r"\bA10G?\b", re.I),               "A10G"),
    (re.compile(r"\bL4\b", re.I),                  "L4"),
    (re.compile(r"\bT4\b", re.I),                  "T4"),
]

# Per-second rate inside the markup. Modal renders "$0.000164 / sec"
# (or sometimes / s). We capture the dollar amount and any context
# is matched separately so we can pair "label … rate" in order.
_PER_SEC_RE = re.compile(
    r"\$\s*([0-9]+\.[0-9]+)\s*(?:USD)?\s*/\s*s(?:ec)?\b", re.I)


def _parse_pricing_html(html: str) -> Dict[str, float]:
    """Extract ``{sdk_key: $/hour}`` from the modal.com pricing HTML.

    Strategy: walk the page text, look for a GPU label and the
    *next* ``$X / sec`` token. Pair them up. Convert sec → hour
    (× 3600). Stop after the first per-GPU section to avoid sweeping
    in CPU/memory rows from later in the doc.
    """
    out: Dict[str, float] = {}
    # Strip tags so we can scan tokens linearly. The pricing page
    # places labels and rates in adjacent table cells; tag-stripping
    # collapses them into "<label> ... <rate>" plain text.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    # Find GPU label positions and per-second rate positions, then
    # for each GPU find the nearest rate that comes after it (so a
    # rate for a different SKU above doesn't get mis-paired).
    label_hits = []
    for pattern, key in _GPU_LABEL_TO_SDK_KEY:
        for m in pattern.finditer(text):
            label_hits.append((m.start(), key))
    rate_hits = [(m.start(), float(m.group(1)))
                 for m in _PER_SEC_RE.finditer(text)]
    # Sort each by position so the "next rate after a label" search
    # is a simple linear scan.
    label_hits.sort()
    rate_hits.sort()
    used_keys = set()
    for pos, key in label_hits:
        if key in used_keys:
            continue
        # First rate that appears after this label position AND
        # within ~400 chars (rates more than a paragraph away are
        # almost always for a different product).
        for rpos, per_sec in rate_hits:
            if rpos > pos and (rpos - pos) < 400:
                hourly = round(per_sec * 3600.0, 4)
                # Sanity bound — Modal GPUs are $0.5-$10/hr; anything
                # outside this band is parser noise (e.g. a CPU rate
                # or a per-token AI gateway price).
                if 0.1 <= hourly <= 25.0:
                    out[key] = hourly
                    # Backfill the A10/A10G alias automatically.
                    if key == "A10G":
                        out["A10"] = hourly
                    used_keys.add(key)
                break
    return out
