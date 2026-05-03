"""Shared widgets / helpers for the per-task model picker.

Two settings surfaces both let the user route writing-tool tasks
(rephrase / plot / worldbuilding / character / general) to a chosen
model:

  * the OS-level CreativeOS Settings dialog
    (:mod:`src.ui.creativeos_settings_dialog`)
  * the writing tool's own Settings dialog's "Per-Task Models" tab
    (:mod:`src.ui.settings_dialog`)

Both want the same picker behaviour: a single combo per task,
populated from the unified model registry (trained + local
pretrained MLX/HF + pinned) plus cloud providers, with an escape
hatch for arbitrary specs. This module owns that picker logic so
the two dialogs can't drift out of sync.

The picker stores values as the canonical task-model spec strings
parsed by :func:`src.config.creativeos_config.parse_task_model_spec`.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QInputDialog, QWidget,
)


def build_task_picker_options() -> List[Tuple[str, Optional[str], bool]]:
    """Return ``(label, spec, is_separator)`` for every picker item.

    Categories appear in this order so the most user-specific items
    (their trained models) show first:
      1. Default fallback
      2. Trained models from the Training Studio
      3. Local pretrained models (MLX + HuggingFace, both built-in
         catalog and any HF ids the user has pinned)
      4. Cloud providers
      5. Custom… (paste any model id / spec)

    Separator items have ``spec=None`` and ``is_separator=True`` so
    the caller can flag them as non-selectable in the combo.
    """
    from src.config.creativeos_config import (
        format_task_model_spec, TASK_CLOUD_PROVIDERS,
    )

    items: List[Tuple[str, Optional[str], bool]] = []
    items.append(("(default — use global model)", "", False))

    try:
        from src.data.model_registry import (
            list_models, KIND_TRAINED, KIND_PRETRAINED_BUILTIN,
            KIND_PRETRAINED_PINNED,
        )
        all_entries = list_models()
    except Exception as e:
        print(f"[per_task_picker] list_models failed: {e}")
        all_entries = []
        KIND_TRAINED = "trained"
        KIND_PRETRAINED_BUILTIN = "pretrained_builtin"
        KIND_PRETRAINED_PINNED = "pretrained_pinned"

    trained = [e for e in all_entries if e.kind == KIND_TRAINED]
    builtin = [e for e in all_entries
               if e.kind == KIND_PRETRAINED_BUILTIN]
    pinned = [e for e in all_entries
              if e.kind == KIND_PRETRAINED_PINNED]

    if trained:
        items.append(("── Trained (Training Studio) ──", None, True))
        for e in trained:
            base = e.base_model or "?"
            items.append((
                f"  {e.display_name}  —  base: {base}",
                format_task_model_spec("trained", name=e.id),
                False,
            ))

    local_pretrained = builtin + pinned
    if local_pretrained:
        items.append(("── Local pretrained models ──", None, True))
        for e in local_pretrained:
            mid = e.base_model or e.id
            framework = (e.framework or "").lower()
            if framework == "mlx":
                spec = format_task_model_spec("mlx", model_id=mid)
                tag = "MLX"
            elif framework == "pytorch":
                spec = format_task_model_spec("hf", model_id=mid)
                tag = "HF"
            else:
                spec = format_task_model_spec("local", model_id=mid)
                tag = "auto"
            size_part = f"  ({e.size_b:.0f}B)" if e.size_b else ""
            items.append((
                f"  {e.display_name}{size_part}  [{tag}]  —  {mid}",
                spec,
                False,
            ))

    items.append(("── Cloud providers ──", None, True))
    cloud_labels = {
        "claude": "Claude (Anthropic)",
        "chatgpt": "ChatGPT (OpenAI)",
        "openai": "OpenAI",
        "gemini": "Gemini (Google)",
    }
    for prov in TASK_CLOUD_PROVIDERS:
        items.append((
            f"  {cloud_labels.get(prov, prov)}  "
            f"(uses model from AI Settings)",
            format_task_model_spec("cloud", provider=prov),
            False,
        ))

    items.append(("── Other ──", None, True))
    items.append(("  Custom… (paste any model id or spec)",
                  "__custom__", False))
    return items


def find_combo_idx_for_spec(combo: QComboBox, spec: str) -> int:
    """Find the combo index whose item matches ``spec``.

    Tries exact item-data match first, then a normalised match (so
    legacy bare names like ``"Foo"`` still select the
    ``"trained:Foo"`` item).
    """
    from src.config.creativeos_config import (
        parse_task_model_spec, format_task_model_spec,
    )
    for i in range(combo.count()):
        if combo.itemData(i) == spec:
            return i
    if spec:
        normalised = parse_task_model_spec(spec)
        kind = normalised.get("kind")
        if kind:
            normalised_str = format_task_model_spec(
                **{**normalised, "kind": kind})
            for i in range(combo.count()):
                if combo.itemData(i) == normalised_str:
                    return i
    return -1


def custom_label_for_spec(spec: str) -> str:
    """Render a friendly label for a spec the picker doesn't know."""
    from src.config.creativeos_config import parse_task_model_spec
    parsed = parse_task_model_spec(spec)
    kind = parsed.get("kind", "")
    if kind == "trained":
        return f"(custom: trained '{parsed.get('name', '')}')"
    if kind in ("hf", "mlx", "local"):
        return f"(custom: {kind} '{parsed.get('model_id', '')}')"
    if kind == "cloud":
        tail = parsed.get("model") or "(default model)"
        return (f"(custom: cloud {parsed.get('provider', '')} "
                f"{tail})")
    return f"(custom: '{spec}')"


def populate_task_combo(combo: QComboBox, current_spec: str) -> Dict:
    """Fill ``combo`` with all picker options + pre-select ``current_spec``.

    Returns a state dict the caller stashes per-row so the save path
    can read back the current selection (and the optional Custom…
    dialog can preserve specs that don't match any enumerated item).

    The state dict keys:
      * ``combo`` — the combo itself
      * ``saved_spec`` — the spec the dialog was opened with
      * ``custom_spec`` — a spec the user pasted via Custom… (empty
        until used)
    """
    combo.clear()
    combo.setMinimumWidth(420)

    for label, spec, is_separator in build_task_picker_options():
        combo.addItem(label, spec)
        if is_separator:
            idx = combo.count() - 1
            model = combo.model()
            item = model.item(idx)
            if item is not None:
                # Disable so the user can't pick the separator.
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsSelectable
                    & ~Qt.ItemFlag.ItemIsEnabled)

    state = {
        "combo": combo,
        "saved_spec": (current_spec or "").strip(),
        "custom_spec": "",
    }

    # Pre-select the saved spec. Exact then normalised match;
    # falls back to inserting a "(custom: …)" item so the user sees
    # what's selected and can keep or change it.
    saved = state["saved_spec"]
    idx = find_combo_idx_for_spec(combo, saved)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    elif saved:
        combo.insertItem(1, custom_label_for_spec(saved), saved)
        combo.setCurrentIndex(1)
    return state


def read_task_combo_spec(state: Dict) -> str:
    """Read a per-task combo's currently-selected spec string.

    Falls back to the user's custom-spec value when the combo's
    currently-selected item is the Custom… sentinel or a separator
    (shouldn't happen — separators are disabled — but defensive).
    """
    combo: QComboBox = state["combo"]
    data = combo.itemData(combo.currentIndex())
    if data == "__custom__" or data is None:
        return state.get("custom_spec") or ""
    return data or ""


def open_custom_spec_dialog(state: Dict, parent: QWidget) -> None:
    """Prompt the user for a free-form spec; update ``state`` + combo.

    Power-user escape hatch that lets the user paste any model id /
    explicit spec the picker hasn't enumerated. Bare HuggingFace
    ids (containing ``/``) are auto-promoted to ``hf:<id>`` so the
    resolver builds a HuggingFace LLMClient instead of mis-routing
    the id through the trained-models registry as a name.

    On Cancel: restores the combo to whatever it was showing before
    the user opened the dialog so they don't get stuck on the
    Custom… sentinel.
    """
    from src.config.creativeos_config import (
        format_task_model_spec, parse_task_model_spec,
    )

    text, ok = QInputDialog.getText(
        parent, "Custom model",
        "Paste a HuggingFace model id, a local path, or a spec "
        "string:\n\n"
        "  • bare HF id   →  treated as local HF\n"
        "  • mlx:<id>      →  Apple-Silicon MLX model\n"
        "  • hf:<id>       →  HuggingFace transformer\n"
        "  • trained:<n>   →  Training Studio name\n"
        "  • cloud:<prov>  →  cloud (claude / chatgpt / gemini)\n"
        "  • cloud:<prov>:<model>   →  cloud + explicit model",
        text=state.get("custom_spec") or state.get("saved_spec") or "")

    combo: QComboBox = state["combo"]
    if not ok:
        # Revert to whatever was selected before opening Custom….
        target = (state.get("custom_spec")
                  or state.get("saved_spec") or "")
        idx = find_combo_idx_for_spec(combo, target)
        if idx < 0:
            idx = 0
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        return

    spec = (text or "").strip()
    if not spec:
        state["custom_spec"] = ""
        combo.blockSignals(True)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        return

    # Bare HF id with a slash → treat as ``hf:`` so the resolver
    # builds a HuggingFace client rather than looking the bare name
    # up in the trained-models registry (where it would miss).
    parsed = parse_task_model_spec(spec)
    if parsed.get("kind") == "trained" and "/" in spec:
        spec = format_task_model_spec("hf", model_id=spec)

    state["custom_spec"] = spec
    idx = find_combo_idx_for_spec(combo, spec)
    if idx < 0:
        combo.insertItem(1, custom_label_for_spec(spec), spec)
        idx = 1
    combo.blockSignals(True)
    combo.setCurrentIndex(idx)
    combo.blockSignals(False)


def attach_custom_handler(state: Dict, parent: QWidget) -> Callable[[int], None]:
    """Build + return a slot wired to the combo's currentIndexChanged.

    When the user picks the Custom… sentinel, opens the spec dialog;
    otherwise no-op (the spec lives directly on the combo's data).
    The caller wires the returned callable to
    ``combo.currentIndexChanged.connect(...)``.
    """
    combo: QComboBox = state["combo"]

    def _on_changed(i: int):
        data = combo.itemData(i)
        if data == "__custom__":
            open_custom_spec_dialog(state, parent)

    return _on_changed
