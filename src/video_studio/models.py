"""Data models for the Video Studio module.

The studio is a node-graph view: each ``Scene`` is a card; ``SceneHop``
links connect cards. Each scene can have many generated ``VideoClip``s
(from one or several backend runs); the user marks a favorite and can
delete the rest. ``CharacterReference`` carries a reusable description
+ seed so character appearance stays consistent across clips.

``VideoStudio`` is the root container that lives on ``WriterProject``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class VideoClip(BaseModel):
    """One generated media file attached to a scene.

    Despite the historical name, a "clip" can be either a video file
    (``clip_type="video"``) or a still image (``clip_type="image_still"``)
    shown for ``duration_seconds``. The studio keeps the path, not
    the bytes. Backends write the file + a JSON sidecar with the
    prompt + backend + parameters.
    """
    id: str = Field(default_factory=lambda: f"clip_{uuid4().hex[:10]}")
    file_path: str = ""
    backend: str = ""
    prompt_at_generation: str = ""
    # For videos this is the actual clip length; for image stills
    # this is how long the still should be displayed when the scene
    # plays / is stitched into the final cut.
    duration_seconds: float = 0.0
    seed: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)
    # Sidecar metadata path (JSON) for inspection / debugging.
    sidecar_path: str = ""
    # True for backends that produced a placeholder rather than
    # actual rendered media. The UI labels these distinctly so the
    # user knows it's not a real render.
    is_placeholder: bool = False
    # "video" (default, backwards compatible) or "image_still".
    # Image stills are converted to a short video clip by the
    # stitcher using their ``duration_seconds`` as the display time.
    clip_type: str = "video"
    notes: str = ""


class ActionImage(BaseModel):
    """One image generated for a single SceneAction.

    A SceneAction can have many candidate images (from multiple
    generation runs, different prompts, etc.) — the user picks
    which ones land in the final slide deck for the scene.
    """
    id: str = Field(default_factory=lambda: f"actimg_{uuid4().hex[:10]}")
    file_path: str = ""
    sidecar_path: str = ""
    backend: str = ""
    prompt_at_generation: str = ""
    seed: Optional[int] = None
    is_placeholder: bool = False
    # When True, this image is included in the scene's slide deck
    # when the scene's ``mode`` is ``"slideshow"``. Multiple images
    # per action MAY be included so writers can sequence a quick
    # internal montage within a single beat.
    included_in_slideshow: bool = True
    display_seconds: float = 3.0
    created_at: datetime = Field(default_factory=datetime.now)


class SceneAction(BaseModel):
    """A discrete beat within a Scene.

    The Scene's overall ``prompt`` describes the whole scene; each
    SceneAction breaks that into smaller verifiable units the writer
    can refine — *"Mara crosses the threshold"*, *"the chamber
    falls silent"*, *"the senior judge stands"*. Backends use the
    action sequence to enrich their video prompt; image-based
    backends generate one image per action when the scene is in
    ``"slideshow"`` mode.
    """
    id: str = Field(default_factory=lambda: f"act_{uuid4().hex[:10]}")
    name: str = ""                       # short verb-phrase
    description: str = ""                # detailed action description
    order: int = 0                       # position in the scene
    # Character and location refs scoped to THIS action. The scene's
    # overall ``character_refs`` still apply; these are the subset
    # actually visible in this beat so backends can target
    # likeness / setting more precisely.
    character_refs: List[str] = Field(default_factory=list)
    location_refs: List[str] = Field(default_factory=list)
    # Free-text additional details — props, weather, lighting cues,
    # camera notes — the writer wants the backend to honor.
    scenery_details: str = ""
    # Source prose excerpt this action was extracted from. Lets the
    # writer see (and edit) the exact passage that motivated this
    # beat — also fed into the per-action image prompt so the
    # backend sees the same source detail.
    prose_excerpt: str = ""
    # How long this action's slide should hold on screen when the
    # slide-deck stitcher walks the scene. 0 means "inherit from
    # Scene.image_display_seconds" — most scenes have a uniform
    # cadence, so the writer only sets this when they want a
    # specific beat to linger or flash by.
    display_seconds: float = 0.0
    # Hand-curated character + setting detail for THIS action.
    # The writer fills these via the editor's lookup buttons or
    # by hand. Both feed into the per-action image / video prompt
    # so the renderer sees the specifics for this beat —
    # separate from the action's ``scenery_details`` (props /
    # lighting cues) and from the scene-level character /
    # setting fields (the scene-wide baseline).
    character_details: str = ""
    setting_details: str = ""
    # Free-form per-action directives appended to the backend
    # prompt for this beat — camera notes, no-text guards,
    # framing tweaks, etc. Layered on top of the scene-level
    # ``additional_instructions`` so the writer can target a
    # specific beat without affecting the rest.
    additional_instructions: str = ""
    # Generated images for this action. Populated when the scene's
    # mode is ``"slideshow"`` and the user clicks "Generate slide
    # deck images" — one or more per action.
    images: List[ActionImage] = Field(default_factory=list)
    favorite_image_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def favorite_image(self) -> Optional[ActionImage]:
        if not self.favorite_image_id:
            return self.images[0] if self.images else None
        for img in self.images:
            if img.id == self.favorite_image_id:
                return img
        return self.images[0] if self.images else None

    def included_images(self) -> List[ActionImage]:
        """Images marked for inclusion in the scene's slide deck."""
        return [img for img in self.images if img.included_in_slideshow]


# Allowed values for ``Scene.mode``. Video is the default — the
# scene generates one video clip per its overall prompt. Slideshow
# breaks the scene into per-action stills the stitcher walks in
# sequence.
SCENE_MODES = ("video", "slideshow")


# Visual style presets the user can pick from. Each entry is
# (label, prompt_phrase) — the label shows up in the toolbar combo,
# the phrase is folded VERBATIM into the backend prompt so the
# rendered visuals match what the user expected when they picked the
# preset. ``""`` (empty) is the sentinel for "no preset; rely on
# the freeform description (or just the genre)".
#
# Phrases are written to compose cleanly into "Style: <phrase>." —
# keep them noun-phrases describing the visual, not directives.
# The director appends the user's ``style_description`` after the
# preset phrase, so writers can layer "rim-lit, shallow depth of
# field" onto any preset without re-typing the base style.
STYLE_PRESETS: tuple = (
    ("", "(no preset — use description only)"),
    ("photo_realistic",
     "photo-realistic, natural lighting, sharp focus, "
     "high-detail textures, cinematic color grading"),
    ("cinematic",
     "cinematic 35mm film look, shallow depth of field, "
     "anamorphic widescreen framing, dramatic key lighting"),
    ("artistic",
     "stylized artistic illustration, painterly brushwork, "
     "rich saturated color, expressive composition"),
    ("oil_painting",
     "classical oil-painting aesthetic, visible brush strokes, "
     "warm chiaroscuro lighting, Old Master color palette"),
    ("watercolor",
     "soft watercolor wash, paper texture, gentle bleed of color, "
     "airy negative space"),
    ("ink_sketch",
     "monochrome ink-and-pencil sketch, crosshatched shading, "
     "raw illustrative linework, minimal color accents"),
    ("comic_book",
     "comic-book panel art, bold inked outlines, halftone "
     "shading, dynamic action posing, saturated primary colors"),
    ("graphic_novel",
     "modern graphic-novel illustration, muted painterly palette, "
     "moody atmospheric lighting, cinematic framing"),
    ("anime",
     "anime / cel-shaded animation style, clean linework, "
     "expressive eyes, vibrant color blocks, dynamic motion lines"),
    ("cartoon",
     "playful 2D cartoon style, bold flat colors, exaggerated "
     "expressive features, simple shape language"),
    ("pixar_3d",
     "modern 3D animated film look (Pixar / DreamWorks), "
     "soft global illumination, stylized character proportions, "
     "vivid color palette"),
    ("noir",
     "high-contrast film-noir black-and-white, deep shadows, "
     "venetian-blind light patterns, smoke and rain atmosphere"),
    ("retro_film",
     "warm 1970s film stock, slight grain, faded saturation, "
     "soft hazy highlights, period-appropriate color science"),
    ("storyboard",
     "rough storyboard sketch, pencil-and-marker rendering, "
     "loose linework, monochrome with key color highlights"),
)


def style_preset_phrase(key: str) -> str:
    """Look up the prompt phrase for a style preset key. Returns
    "" for the no-preset sentinel or any unknown key — callers
    treat that as "writer described it themselves"."""
    if not key:
        return ""
    for k, phrase in STYLE_PRESETS:
        if k == key and k:
            return phrase
    return ""


def style_preset_label(key: str) -> str:
    """Human-readable label for a preset key (the second tuple
    item when the key is empty serves as the dropdown's first
    entry; for real keys we render the key with underscores
    swapped for spaces and title-cased)."""
    if not key:
        return "(no preset)"
    return key.replace("_", " ").title()


class Narration(BaseModel):
    """A spoken-audio track attached to a scene.

    Three production paths:
      * ``source="tts"``: ``text`` was synthesized by ``tts_backend``
        (and optionally a specific ``tts_voice``).
      * ``source="imported"``: a pre-recorded audio file the user
        dragged in (text may still be set as a transcript).
      * ``source="recorded"``: in-app recording (future).

    ``duration_seconds`` is best-effort — set by the TTS backend
    from the synth result, or probed via ffprobe on import. May be
    0 when the duration is unknown; downstream stitcher will fall
    back to ``-shortest`` behavior in that case.
    """
    id: str = Field(default_factory=lambda: f"narr_{uuid4().hex[:10]}")
    source: str = "tts"               # "tts" | "imported" | "recorded"
    text: str = ""                     # synthesis input / transcript
    audio_path: str = ""               # absolute path to the .mp3/.wav
    duration_seconds: float = 0.0
    tts_backend: str = ""
    tts_voice: str = ""
    sidecar_path: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


# Transitions the chapter-deck editor can place between adjacent
# segments. Mapped 1:1 onto ffmpeg's ``xfade`` filter options so
# the stitcher passes them through directly. ``cut`` is the
# zero-frame default (no crossfade) used by the legacy stitcher.
CHAPTER_TRANSITIONS = (
    ("cut", "Hard cut (no transition)"),
    ("fade", "Crossfade — soft blend"),
    ("fadeblack", "Fade through black"),
    ("fadewhite", "Fade through white"),
    ("dissolve", "Dissolve — pixel mix"),
    ("slideleft", "Slide left"),
    ("slideright", "Slide right"),
    ("slideup", "Slide up"),
    ("slidedown", "Slide down"),
    ("wipeleft", "Wipe left"),
    ("wiperight", "Wipe right"),
    ("circleopen", "Circle open"),
    ("circleclose", "Circle close"),
    ("radial", "Radial wipe"),
)


class ChapterDeckSegment(BaseModel):
    """One segment in the chapter-deck editor's timeline.

    Wraps a reference to a scene (``scene_id``) OR an arbitrary
    file path (``custom_path``) the writer dropped in to fill a
    gap. Holds the transition that plays INTO this segment (so the
    first segment's ``transition_in`` is ignored). Optional
    ``duration_override`` lets the writer hold a still or trim a
    clip without re-rendering the scene.
    """
    id: str = Field(
        default_factory=lambda: f"seg_{uuid4().hex[:10]}")
    scene_id: Optional[str] = None
    custom_path: str = ""
    label: str = ""
    transition_in: str = "cut"
    transition_seconds: float = 0.7
    duration_override: float = 0.0
    order: int = 0


class ChapterDeck(BaseModel):
    """Editable chapter-level deck.

    Lives on the studio so the writer can iterate on a finished
    deck — re-order, retime, add transitions, layer voiceover —
    without losing the per-scene work. ``segments`` is the ordered
    list of clips that play; ``voiceovers`` are master-timeline
    voiceover takes mixed over everything; ``transition_default``
    is applied to every segment that hasn't been overridden.
    """
    id: str = Field(
        default_factory=lambda: f"deck_{uuid4().hex[:10]}")
    chapter_id: str = ""
    name: str = ""
    segments: List[ChapterDeckSegment] = Field(default_factory=list)
    voiceovers: List["VoiceoverSegment"] = Field(default_factory=list)
    transition_default: str = "fade"
    transition_seconds_default: float = 0.7
    output_width: int = 1280
    output_height: int = 720
    output_fps: int = 30
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class SlidePage(BaseModel):
    """One page of a SlideDeckProject — an image with a narration
    take, a duration the stitcher honors, and optional script text
    the AI timing pass measures.

    ``image_path`` is the slide visual (PNG / JPG / WebP). Each
    page has at most one ``audio_path`` (record-and-replace flow);
    ``locked_duration`` lets the writer keep a slide at exactly N
    seconds even if a longer audio take lands on it.
    """
    id: str = Field(
        default_factory=lambda: f"page_{uuid4().hex[:10]}")
    index: int = 0
    label: str = ""
    image_path: str = ""
    audio_path: str = ""
    audio_duration_seconds: float = 0.0
    duration_seconds: float = 4.0
    locked_duration: bool = False
    script_text: str = ""
    group_id: Optional[str] = None
    # Transition that plays INTO this slide. ``cut`` (the default
    # on the first slide) is no-op; any other value is an xfade
    # name (matches ``CHAPTER_TRANSITIONS``) for the MP4 export
    # AND a PowerPoint transition type for the PPTX export.
    transition_in: str = "cut"
    transition_seconds: float = 0.7
    # Source provenance — when the page was seeded from a scene's
    # action, we remember which one so re-syncs (regenerating
    # action images, etc.) can find the right slide later.
    source_scene_id: Optional[str] = None
    source_action_id: Optional[str] = None
    # Timeline position inside the slide's group, measured in
    # seconds from the start of the group's overlay audio. When
    # ``None``, the slide hasn't been dropped onto the group
    # timeline yet — the group editor shows it in the "available
    # slides" tray. When set, the slide is rendered as a block
    # on the timeline starting at this offset; its visible
    # duration runs until the NEXT placed slide (or to the audio
    # end for the last placed slide).
    start_time_seconds_in_group: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class GroupAudioClip(BaseModel):
    """One take inside a group's audio track. Writers record
    line-by-line into multiple clips; the group editor stitches
    them into the rendered ``overlay_audio_path`` with auto
    crossfades, so playback + export still operate on a single
    file. The clips list is the *source of truth*; the rendered
    file is a cache that gets re-built whenever the list
    changes."""
    id: str = Field(
        default_factory=lambda: f"aclip_{uuid4().hex[:10]}")
    # Writer-visible label (auto "Take N" by default).
    label: str = ""
    # Path to the raw take on disk. Each Record click writes a
    # fresh WAV here; deleting a clip just drops the entry,
    # the file stays unless the writer explicitly purges it.
    audio_path: str = ""
    duration_seconds: float = 0.0
    # Non-destructive trim inside the source file.
    trim_in_seconds: float = 0.0
    # 0.0 = play to end of source (matches the legacy overlay
    # trim semantics so the renderer doesn't need to special-
    # case "no trim").
    trim_out_seconds: float = 0.0
    # Per-clip gain in dB (volume= filter). 0 = no change.
    gain_db: float = 0.0
    # Position on the GROUP's timeline (seconds from the
    # start of the composed overlay). The clip starts playing
    # at this offset; ``compose_clips`` uses ffmpeg's
    # ``adelay`` filter to push the source there before
    # ``amix`` sums everything. ``None`` is the legacy
    # "auto-place sequentially" mode — the migration path on
    # group-editor open assigns concrete values so the rest
    # of the code only sees positioned clips.
    start_time_seconds: Optional[float] = None
    # Per-clip fade in / fade out, baked into the recompose
    # via ffmpeg ``afade``. Replaces the per-overlay fade
    # that lived on the audio bar's right-click menu — those
    # used to vanish on the next recompose because they
    # touched the rendered cache, not the clips.
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    # LEGACY — kept on the model for backward-compat with
    # decks that pre-date positional placement. The migration
    # path translates ``crossfade_seconds`` into the equivalent
    # overlap between adjacent clips' start times, then the
    # field stops mattering.
    crossfade_seconds: float = 0.15
    # Lane / track this clip lives on. Default ``0`` keeps every
    # existing saved deck on a single primary track; setting a
    # higher index stacks the clip in a parallel lane so the
    # writer can layer music + SFX + narration without them
    # contending for the same timeline slot. ``compose_clips``
    # mixes all tracks together via ``amix``; the timeline
    # widget renders one visual lane per distinct ``track_index``.
    track_index: int = 0
    # Per-clip de-esser intensity (0..1). 0 = off (default),
    # 0.4–0.6 is the usual range for taming sibilance. When
    # set, OVERRIDES the lane-level
    # ``SlideGroup.track_deesser_intensity`` for this clip —
    # writers can dial in one harsh take without affecting
    # the rest of the lane.
    deesser_intensity: float = 0.0
    # Per-clip noise reduction floor in dB (afftdn ``nf=``).
    # 0 = off (default); a negative value (-25 typical) tells
    # afftdn to treat anything below that dB as noise and
    # attenuate it. More negative = more aggressive.
    denoise_floor_db: float = 0.0
    # Writer-managed backup of the clip's editable settings.
    # Saved on demand via the right-click menu's "📌 Save
    # backup"; restored via "↺ Restore from backup". Single
    # slot per clip (overwrites prior backup) so the model
    # stays small even on big decks. Shape:
    #   {"saved_at": "<isoformat>",
    #    "fields": {field_name: value, ...}}
    # ``None`` = no backup has been saved yet.
    backup_snapshot: Optional[dict] = None
    created_at: datetime = Field(default_factory=datetime.now)


class SlideGroup(BaseModel):
    """A named cluster of slides that share editorial intent —
    "Opening", "Confrontation", "Coda". Groups let the writer
    distribute a total duration evenly across member slides or
    apply a shared transition / treatment in one go."""
    id: str = Field(
        default_factory=lambda: f"sgrp_{uuid4().hex[:10]}")
    name: str = ""
    page_ids: List[str] = Field(default_factory=list)
    # When > 0, the editor evenly distributes this duration across
    # the unlocked pages in the group (locked pages keep their
    # exact times; the remainder splits across the rest).
    target_total_seconds: float = 0.0
    # Source-of-truth list of recorded takes / imported clips
    # that make up the group's audio track. Writers record
    # line-by-line; on save, ``compose_clips`` renders them
    # into ``overlay_audio_path`` with auto-crossfades, and
    # playback + export read from that rendered file. An empty
    # list means "no audio yet" — first Record click appends
    # the first clip.
    audio_clips: List["GroupAudioClip"] = Field(default_factory=list)
    # Rendered overlay — the result of stitching ``audio_clips``
    # together. Single file so the existing playback / export
    # pipelines stay unchanged. Legacy decks that pre-date the
    # clips refactor still carry an ``overlay_audio_path`` set
    # directly; the group editor migrates those into a single-
    # entry ``audio_clips`` list on first open.
    overlay_audio_path: str = ""
    overlay_audio_duration_seconds: float = 0.0
    # Non-destructive trim of the overlay audio. The timeline
    # widget exposes draggable in / out handles; the export
    # pipeline reads these values and applies an ffmpeg ``-ss``
    # / ``-t`` on the way out. ``overlay_trim_out_seconds == 0``
    # means "play to the end of the file" so we don't have to
    # rewrite the value every time the audio is re-recorded.
    overlay_trim_in_seconds: float = 0.0
    overlay_trim_out_seconds: float = 0.0
    # When True, the group's last slide auto-stretches so the
    # group's total duration matches the overlay audio's length
    # (minus any locked-slide times). Keeps the visual + audio
    # in sync without manually retyping the last slide's seconds.
    fill_last_slide_to_audio: bool = False
    # Writer-facing preference: when True, inline audio
    # transforms (right-click on the audio bar in the group
    # editor) write a NEW sibling file and switch the overlay
    # to it. When False (default), each transform overwrites
    # the source WAV in place. Persisted on the group so the
    # writer doesn't have to re-pick the mode on every reopen.
    save_audio_edits_as_new: bool = False
    # Per-track gain in dB, keyed by the integer ``track_index``
    # used on GroupAudioClip. Missing keys default to 0 dB
    # (unity). Lets writers raise / drop a whole lane (e.g.
    # ducking a music bed under the narration) without touching
    # individual clips. ``compose_clips`` applies these on the
    # per-clip ``volume=`` filter chain.
    track_gain_db: Dict[int, float] = Field(
        default_factory=dict)
    # Friendly names for tracks, keyed by ``track_index``. Used
    # in the timeline's left-side track strip + the right-click
    # "Move to track" submenu. Missing keys fall back to
    # "Track N" so writers don't see blanks.
    track_names: Dict[int, str] = Field(default_factory=dict)
    # Per-track de-esser intensity, keyed by ``track_index``.
    # 0.0 = filter off (default); positive values tame
    # sibilance in the 5–8 kHz band via ffmpeg's ``deesser``
    # filter. Most writers want 0.4–0.6 for harsh "ess" /
    # "sh" reductions; >0.8 starts to muffle dialog. Missing
    # keys mean "no de-essing on that lane."
    track_deesser_intensity: Dict[int, float] = Field(
        default_factory=dict)
    # Inter-group transition INTO this group from the
    # previous group in deck order. ``"cut"`` (default) =
    # hard concat (no crossfade); other values match
    # ffmpeg's xfade transition names ("fade", "dissolve",
    # "wipeleft", etc.). ``inter_group_transition_seconds``
    # = 0 also means "hard cut" regardless of name. The
    # deck preview / export concat applies xfade to video +
    # acrossfade to audio at this boundary. Ignored for the
    # very first group in the deck.
    inter_group_transition_in: str = "cut"
    inter_group_transition_seconds: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def _migrate_legacy_audio(self) -> "SlideGroup":
        """Bring legacy-shape groups forward to the multi-clip
        timeline model.

        Two repairs, both idempotent so re-validating a fresh
        group is a no-op:

        1. **Promote ``overlay_audio_path`` → ``audio_clips``.**
           Older decks (pre-DAW timeline) stored a single rendered
           overlay WAV directly on the group with no clips list.
           The group editor + export pipeline now read
           ``audio_clips`` as the source of truth and re-render
           ``overlay_audio_path`` as a cache. Without this
           promotion, an old project loaded by code that's never
           opened the group editor (export, preview, deck stitch)
           sees an empty timeline AND a stale overlay — and only
           the overlay reaches the rendered MP4. Promoting at
           model-load time means every downstream consumer sees
           the same shape regardless of UI entry point.

        2. **Backfill ``start_time_seconds`` on clips.** Clips
           authored before positional placement carried no
           ``start_time_seconds`` (the field was added with the
           timeline rewrite). Walk in list order, honoring the
           legacy ``crossfade_seconds`` overlap so the migrated
           positions match what the writer last heard on
           playback. Clips that already have a value win — never
           rewrite the writer's explicit placement.

        The UI's ``_maybe_migrate_overlay_to_clips`` /
        ``_reconcile_group_page_ids`` (group_editor_dialog.py)
        stay in place as defense-in-depth — they handle stale
        in-memory state the model layer wouldn't see (e.g. a
        writer recording then immediately closing without a
        validator pass).
        """
        if not self.audio_clips and self.overlay_audio_path:
            self.audio_clips = [
                GroupAudioClip(
                    label="Take 1",
                    audio_path=self.overlay_audio_path,
                    duration_seconds=float(
                        self.overlay_audio_duration_seconds
                        or 0.0),
                    trim_in_seconds=float(
                        self.overlay_trim_in_seconds or 0.0),
                    trim_out_seconds=float(
                        self.overlay_trim_out_seconds or 0.0),
                    start_time_seconds=0.0,
                )
            ]
        if self.audio_clips:
            running = 0.0
            for i, clip in enumerate(self.audio_clips):
                if clip.start_time_seconds is not None:
                    kept = max(
                        0.0,
                        float(clip.duration_seconds or 0.0)
                        - float(clip.trim_in_seconds or 0.0)
                        - float(clip.trim_out_seconds or 0.0))
                    running = (
                        float(clip.start_time_seconds) + kept)
                    continue
                xf = float(clip.crossfade_seconds or 0.0)
                start = (
                    0.0 if i == 0 else max(0.0, running - xf))
                clip.start_time_seconds = start
                kept = max(
                    0.0,
                    float(clip.duration_seconds or 0.0)
                    - float(clip.trim_in_seconds or 0.0)
                    - float(clip.trim_out_seconds or 0.0))
                running = start + kept
        return self


class SlideDeckProject(BaseModel):
    """An editable slide deck — built from a chapter's scenes /
    action favorites, with per-slide audio + timing + groups.

    The slide editor uses this as the live model; ``working_dir``
    is where extracted slide images and recorded audio land. On
    export the stitcher walks pages in order, mixes each page's
    audio with its image-as-still segment, and concatenates."""
    id: str = Field(
        default_factory=lambda: f"sdp_{uuid4().hex[:10]}")
    name: str = ""
    chapter_id: str = ""
    working_dir: str = ""
    pages: List[SlidePage] = Field(default_factory=list)
    groups: List[SlideGroup] = Field(default_factory=list)
    # Average reading speed used by ``suggest_timings_from_script``
    # (words per minute). 150 wpm is a slightly slow voiceover
    # pace, which gives a forgiving timing budget; writers can
    # bump up if they speak faster.
    wpm_estimate: int = 150
    # Microphone the writer last picked in this editor session.
    # Stored as the device's description string (e.g. "MacBook Pro
    # Microphone"). Empty falls back to the system default at
    # record time. Resolving by description gracefully degrades
    # when the writer moves to a different machine.
    microphone_device_name: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def _migrate_legacy_group_placements(self) -> "SlideDeckProject":
        """Auto-place pages onto the group timeline for decks
        written before per-page ``start_time_seconds_in_group``
        existed.

        New semantics: ``page.start_time_seconds_in_group is
        None`` means "available in the tray, not on the
        timeline." Old decks have every grouped page at
        ``None`` because the field didn't exist when they were
        saved — without migration those pages all land in the
        tray on first reload and the writer sees an empty
        timeline despite having designed a sequence.

        Per-group rule: if EVERY page in the group has
        ``start_time_seconds_in_group is None``, treat that as
        a legacy save and place them sequentially in
        ``page_ids`` order at running offsets summed from
        ``duration_seconds``. If ANY page is already placed,
        the writer has used the new editor — respect their
        layout and leave the unplaced pages in the tray.

        Idempotent: once a deck has been migrated and saved,
        every page has a concrete offset (or the writer
        deliberately moved one back to the tray), so the all-
        None precondition fails and this loop becomes a
        no-op.
        """
        if not self.groups:
            return self
        pages_by_id = {p.id: p for p in self.pages}
        for group in self.groups:
            ids = list(group.page_ids or [])
            group_pages = [
                pages_by_id[pid]
                for pid in ids if pid in pages_by_id]
            if not group_pages:
                continue
            any_placed = any(
                p.start_time_seconds_in_group is not None
                for p in group_pages)
            if any_placed:
                continue
            running = 0.0
            for page in group_pages:
                page.start_time_seconds_in_group = round(
                    running, 3)
                running += max(
                    0.25, float(page.duration_seconds or 0.0))
        return self


class VideoEditorSession(BaseModel):
    """One open session of the video editor — the writer's
    voiceover takes and ancillary state for a specific MP4 file.

    Looked up by ``source_path`` so closing + reopening the
    editor on the same file picks up the exact takes (with
    every trim / gain / fade / start-at preserved) the writer
    left behind. Working dir holds the recorded WAVs;
    ``voiceovers`` references them by absolute path so the
    project stays self-contained.
    """
    id: str = Field(
        default_factory=lambda: f"ves_{uuid4().hex[:10]}")
    source_path: str = ""
    working_dir: str = ""
    voiceovers: List["VoiceoverSegment"] = Field(
        default_factory=list)
    # Persisted microphone pick — same shape as the slide deck's
    # field. Looked up by description; empty falls back to the
    # system default at record time.
    microphone_device_name: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class VoiceoverSegment(BaseModel):
    """One audio clip placed on the scene's voiceover timeline.

    The scene's visuals (video clip, image still, or slide deck)
    run from 0 → ``scene.effective_duration``. Each segment
    references a SOURCE audio file (the recording or import) and
    plays a slice of it at a chosen ``start_at`` on that timeline.
    Multiple segments mix together — writers can layer narration
    over ambient music, drop a beat-specific cue right before a
    slide flip, or thread several short reads across a longer
    video.

    Sound-edit metadata is intentionally simple — gain in dB, fade
    in/out in seconds, and trim points within the source — so the
    UI can offer immediate sliders and the stitcher can render
    everything in a single ffmpeg ``filter_complex`` pass at mux
    time.
    """
    id: str = Field(default_factory=lambda: f"vo_{uuid4().hex[:10]}")
    label: str = ""                    # human label ("intro", "stinger")
    audio_path: str = ""               # absolute path to the source file
    sidecar_path: str = ""
    source: str = "imported"          # "imported" | "recorded" | "tts"
    # Where on the scene's timeline this segment begins, in seconds.
    start_at: float = 0.0
    # Trim points within the SOURCE audio. ``in_point`` clips off
    # the head; ``out_point`` clips the tail (0.0 means "to end").
    # The played duration is roughly ``out_point - in_point`` if
    # out_point > in_point, else ``source_duration - in_point``.
    in_point: float = 0.0
    out_point: float = 0.0
    # Source media length probed via ffprobe at import. Lets the
    # editor render a timeline ruler accurately without re-probing
    # on every redraw.
    source_duration_seconds: float = 0.0
    # Sound controls. ``gain_db`` is amplification (negative =
    # quieter, 0 = unchanged, +6 ≈ 2× perceived volume). Fades use
    # linear curves so the stitcher's afade filter does the right
    # thing without extra config.
    gain_db: float = 0.0
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    # De-esser intensity. 0.0 = off (default); 0.4–0.6 is the
    # usual range for taming sibilance on close-mic'd dialog.
    # Stitcher applies ffmpeg's ``deesser`` filter per
    # segment so the writer can dial it in on top of an
    # otherwise good take.
    deesser_intensity: float = 0.0
    muted: bool = False
    # Writer-managed backup of the take's editable settings.
    # Saved via the video editor's 📌 Backup button; restored
    # via ↺ Restore. Single slot per segment — the writer
    # snapshots a state they like before experimenting and
    # rolls back if the experiment turned out worse. Shape
    # mirrors GroupAudioClip's ``backup_snapshot``:
    #   {"saved_at": "<isoformat>",
    #    "fields": {field_name: value, ...}}
    backup_snapshot: Optional[dict] = None
    # Slide anchoring — when the scene is in slideshow mode the
    # writer can pin a segment to start exactly at the chosen
    # slide's transition. Stitcher resolves the slide's start
    # time at mux time, so the segment automatically moves if the
    # writer changes per-action display_seconds. None → use the
    # raw ``start_at`` time instead.
    anchored_to_action_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def effective_duration(self) -> float:
        """Length of the slice this segment plays. 0 means
        "to end of source" when source_duration is unknown."""
        if self.out_point > self.in_point > 0:
            return max(0.0, self.out_point - self.in_point)
        if self.out_point > 0:
            return max(0.0, self.out_point - self.in_point)
        if self.source_duration_seconds > 0:
            return max(0.0,
                       self.source_duration_seconds - self.in_point)
        return 0.0


# Valid handlers for video-vs-audio length mismatches. The stitcher
# reads ``Scene.video_audio_mismatch`` to pick one when muxing.
VIDEO_AUDIO_MISMATCH_MODES = (
    "trim",            # cut whichever stream is longer to match (-shortest)
    "loop",            # repeat the video to cover narration audio
    "fade_extend",     # hold last frame of video, fading to black to cover audio
    "extend_silent",   # pad audio with silence to match video length
)


class Scene(BaseModel):
    """A single scene card on the studio canvas.

    Position is grid-cell coordinates, not pixels. The canvas
    converts to pixels at render time so changing the cell size
    doesn't move scenes.
    """
    id: str = Field(default_factory=lambda: f"scene_{uuid4().hex[:10]}")
    name: str = ""
    description: str = ""           # human-readable scene description
    prompt: str = ""                # video-generation prompt
    # Optional anchor back to a chapter — lets the AI director pull
    # focused RAG / plot context when the user asks for help editing.
    chapter_id: Optional[str] = None
    chapter_number: Optional[int] = None
    # Characters present in the scene; used to attach reference info
    # at generation time so characters render consistently.
    character_refs: List[str] = Field(default_factory=list)
    # Generation outputs.
    clips: List[VideoClip] = Field(default_factory=list)
    favorite_clip_id: Optional[str] = None
    # Position on the canvas grid. (col, row) zero-indexed.
    grid_col: int = 0
    grid_row: int = 0
    # Per-scene target duration overrides the studio default. None
    # means "use VideoStudio.default_duration_seconds". Lets users
    # ask the LLM for a 15s establishing shot and a 4s reaction
    # beat in the same chapter without retuning the global default.
    target_duration_seconds: Optional[float] = None
    # Display time for image stills generated by an ImageBackend.
    # Separate field from ``target_duration_seconds`` because a
    # scene might have BOTH a video clip (for the live render) and
    # an image still (as a fallback or storyboard frame), each with
    # its own appropriate length.
    image_display_seconds: float = 4.0
    # Per-action breakdown. When populated, backends use these as
    # the structural skeleton for the scene: video backends append
    # the action sequence to their prompt for richer instruction;
    # image backends in slideshow mode generate one image per
    # action. Empty list means the scene is treated as a single
    # beat described only by ``prompt``.
    actions: List["SceneAction"] = Field(default_factory=list)
    # "video" → generate a single video clip per the scene's
    # overall prompt. "slideshow" → generate one image per
    # SceneAction; the stitcher walks the selected images as a
    # slide deck.
    mode: str = "video"
    # Chapter prose excerpt the user chose via "Pull from chapter".
    # Persists across sessions so the picker can pre-select what
    # the user already approved, and downstream features (action
    # extraction, AI rewrites) have a stable source to ground in.
    source_prose: str = ""
    # Hand-curated character + setting detail blocks. The writer
    # fills these in directly (or via the editor's "+ Lookup"
    # buttons that pull from project.characters /
    # project.worldbuilding.places). Folded into every backend
    # prompt so the model sees the writer's authoritative
    # description — independent of any LLM enhancer.
    character_details: str = ""
    setting_details: str = ""
    # Free-form additional instructions appended to the backend
    # prompt — aspect ratio, framing notes, "no text", "low-angle
    # shot", any directive the writer wants the renderer to honor
    # but doesn't fit the structured fields above.
    additional_instructions: str = ""
    # Optional narration track (TTS or imported audio). When set, the
    # stitcher mixes it into the scene's clip using the rule named by
    # ``video_audio_mismatch`` to reconcile any length difference.
    narration: Optional[Narration] = None
    # Voiceover timeline — zero or more audio clips arranged across
    # the scene's visual duration. Mixed by the stitcher into a
    # single audio track at mux time. Coexists with the legacy
    # single-track ``narration`` field for backward compatibility:
    # when both are set, the stitcher mixes them.
    voiceover_segments: List["VoiceoverSegment"] = Field(
        default_factory=list)
    # How to reconcile video length vs. narration audio length.
    # Defaults to "trim" — the safest, matches the default ffmpeg
    # behavior. Other options:
    #   * loop          → repeat video underneath longer narration
    #   * fade_extend   → hold last frame fading to black for audio tail
    #   * extend_silent → pad audio with silence to match video length
    video_audio_mismatch: str = "trim"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def effective_duration(
        self, studio_default: float,
    ) -> float:
        """Resolve the duration this scene should render at.

        ``target_duration_seconds`` wins when set; falls back to the
        studio's global default otherwise. Always returns a positive
        number ≥ 1.0 so backends don't get asked for 0-second clips.
        """
        if (self.target_duration_seconds is not None
                and self.target_duration_seconds > 0):
            return max(1.0, float(self.target_duration_seconds))
        return max(1.0, float(studio_default))

    def add_clip(self, clip: VideoClip) -> None:
        self.clips.append(clip)
        if self.favorite_clip_id is None:
            self.favorite_clip_id = clip.id
        self.updated_at = datetime.now()

    def remove_clip(self, clip_id: str) -> bool:
        before = len(self.clips)
        self.clips = [c for c in self.clips if c.id != clip_id]
        if self.favorite_clip_id == clip_id:
            self.favorite_clip_id = (
                self.clips[0].id if self.clips else None)
        self.updated_at = datetime.now()
        return len(self.clips) != before

    # ---- action helpers ----
    def add_action(
        self,
        name: str = "",
        description: str = "",
        character_refs: Optional[List[str]] = None,
        location_refs: Optional[List[str]] = None,
    ) -> "SceneAction":
        """Append a SceneAction at the end of this scene's list."""
        action = SceneAction(
            name=name.strip(),
            description=description.strip(),
            character_refs=list(character_refs or []),
            location_refs=list(location_refs or []),
            order=len(self.actions),
        )
        self.actions.append(action)
        self.updated_at = datetime.now()
        return action

    def remove_action(self, action_id: str) -> bool:
        before = len(self.actions)
        self.actions = [a for a in self.actions if a.id != action_id]
        # Re-number remaining actions so order stays dense.
        for i, a in enumerate(self.actions):
            a.order = i
        if len(self.actions) != before:
            self.updated_at = datetime.now()
            return True
        return False

    def move_action(self, action_id: str, delta: int) -> bool:
        """Shift an action up/down by ``delta`` slots; renumbers."""
        for i, a in enumerate(self.actions):
            if a.id == action_id:
                new_i = max(0, min(len(self.actions) - 1, i + delta))
                if new_i == i:
                    return False
                self.actions.insert(new_i, self.actions.pop(i))
                for j, b in enumerate(self.actions):
                    b.order = j
                self.updated_at = datetime.now()
                return True
        return False

    def is_slideshow(self) -> bool:
        return self.mode == "slideshow"

    def favorite_clip(self) -> Optional[VideoClip]:
        if not self.favorite_clip_id:
            return self.clips[0] if self.clips else None
        for c in self.clips:
            if c.id == self.favorite_clip_id:
                return c
        return self.clips[0] if self.clips else None


class SceneHop(BaseModel):
    """A directed edge from one scene to another on the canvas.

    Hops are the "connect cards" the user described. They convey
    sequence/flow — e.g., scene A comes before B. Hops are used by
    the stitcher to determine assembly order when the user picks
    "stitch all favorites along this path".
    """
    id: str = Field(default_factory=lambda: f"hop_{uuid4().hex[:10]}")
    from_scene_id: str
    to_scene_id: str
    label: str = ""  # optional — e.g., "then", "cut to", "flashback"


class CharacterReference(BaseModel):
    """Reusable character info attached at video-generation time.

    A backend that supports character grounding receives this whole
    block as context, ensuring the character renders the same way
    across scenes / chapters. ``seed`` is for backends that support
    deterministic generation given a seed.
    """
    id: str = Field(default_factory=lambda: f"chref_{uuid4().hex[:10]}")
    name: str
    description: str = ""
    appearance_prompt: str = ""    # terse appearance for the backend
    reference_image_path: str = ""  # optional reference still
    seed: Optional[int] = None      # for deterministic backends
    notes: str = ""


class VideoStudio(BaseModel):
    """Root container — lives on the WriterProject.

    Scenes and hops are stored as flat lists; lookups by id happen
    through helpers. ``backend_preference`` records the last
    backend the user selected so we restore it across sessions.
    ``grid_dimensions`` lets the user resize the canvas grid.
    """
    scenes: List[Scene] = Field(default_factory=list)
    hops: List[SceneHop] = Field(default_factory=list)
    # Chapter-deck editor projects — saved across sessions so the
    # writer can come back to a half-edited finished deck without
    # losing transitions, voiceover takes, or reorders.
    chapter_decks: List["ChapterDeck"] = Field(default_factory=list)
    # Slide-deck editor projects — one per chapter the writer has
    # opened in the slide editor. Persists per-slide audio takes,
    # script text, durations, and groups across sessions.
    slide_decks: List["SlideDeckProject"] = Field(default_factory=list)
    # Video-editor session per stitched MP4. Persists every
    # voiceover take + its trim / gain / fade / start_at so the
    # writer can close the editor mid-edit and pick up where
    # they left off — same flow as the slide-deck editor.
    video_editor_sessions: List["VideoEditorSession"] = Field(
        default_factory=list)
    character_references: List[CharacterReference] = Field(
        default_factory=list)
    backend_preference: str = ""
    grid_cols: int = 6   # canvas grid column count
    grid_rows: int = 8   # canvas grid row count
    # Default video length the AI director should aim for, in
    # seconds. Should be "enough to read the scene" — the studio's
    # design goal.
    default_duration_seconds: float = 8.0
    # Visual style applied to every scene's render. ``style_preset``
    # is the short label the user picked from a dropdown (one of
    # ``STYLE_PRESETS``); ``style_description`` is freeform text the
    # writer adds on top to embellish ("with practical lens flares",
    # "always rim-lit", etc.). Both are folded into the prompt for
    # every backend call so look-and-feel stays consistent across
    # the board. Empty preset → "(no preset)", which falls back to
    # the writer's description plus the project's genre alone.
    style_preset: str = ""
    style_description: str = ""
    # When True, the studio asks the LLM to translate the
    # structured composed prompt into proper artwork-direction
    # language (target-aware: image-style for image renders,
    # video-style for clip renders) before sending to the backend.
    # Falls back to the raw composed prompt on any LLM failure or
    # when no LLM is wired — backends always receive SOMETHING
    # usable.
    use_ai_prompt_refinement: bool = True
    # The chapter the writer was last working on inside the
    # studio. When set, the canvas filters to that chapter's
    # scenes, new scenes inherit its id, and the slide / deck
    # editors skip their chapter picker. Empty = "all
    # chapters" (the legacy mixed view). Stored on the studio
    # so it sticks across project close + reopen — the writer
    # comes back to the same chapter they left.
    active_chapter_id: str = ""

    # ---- scene helpers ----
    def get_scene(self, scene_id: str) -> Optional[Scene]:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        return None

    def add_scene(self, scene: Scene) -> Scene:
        # Place at first free cell if the proposed cell is occupied.
        if self._cell_occupied(scene.grid_col, scene.grid_row,
                               exclude_id=scene.id):
            col, row = self._first_free_cell()
            scene.grid_col, scene.grid_row = col, row
        self.scenes.append(scene)
        return scene

    def delete_scene(self, scene_id: str) -> bool:
        before = len(self.scenes)
        self.scenes = [s for s in self.scenes if s.id != scene_id]
        # Cascade: drop hops that touched the deleted scene.
        self.hops = [
            h for h in self.hops
            if h.from_scene_id != scene_id and h.to_scene_id != scene_id]
        return len(self.scenes) != before

    def move_scene(self, scene_id: str, col: int, row: int) -> bool:
        s = self.get_scene(scene_id)
        if s is None:
            return False
        # Bound check + occupancy check.
        col = max(0, min(self.grid_cols - 1, col))
        row = max(0, min(self.grid_rows - 1, row))
        if self._cell_occupied(col, row, exclude_id=scene_id):
            return False
        s.grid_col, s.grid_row = col, row
        s.updated_at = datetime.now()
        return True

    def _cell_occupied(
        self, col: int, row: int, exclude_id: str = "",
    ) -> bool:
        for s in self.scenes:
            if s.id == exclude_id:
                continue
            if s.grid_col == col and s.grid_row == row:
                return True
        return False

    def _first_free_cell(self) -> Tuple[int, int]:
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                if not self._cell_occupied(col, row):
                    return col, row
        # All cells full — expand grid by one row and use the first
        # cell of the new row.
        self.grid_rows += 1
        return 0, self.grid_rows - 1

    # ---- hop helpers ----
    def add_hop(
        self,
        from_id: str,
        to_id: str,
        label: str = "",
    ) -> Optional[SceneHop]:
        if from_id == to_id:
            return None  # no self-loops
        if not self.get_scene(from_id) or not self.get_scene(to_id):
            return None
        # Dedupe: don't add a duplicate hop with the same direction.
        for h in self.hops:
            if h.from_scene_id == from_id and h.to_scene_id == to_id:
                return h
        hop = SceneHop(
            from_scene_id=from_id, to_scene_id=to_id, label=label)
        self.hops.append(hop)
        return hop

    def delete_hop(self, hop_id: str) -> bool:
        before = len(self.hops)
        self.hops = [h for h in self.hops if h.id != hop_id]
        return len(self.hops) != before

    def hops_out_of(self, scene_id: str) -> List[SceneHop]:
        return [h for h in self.hops if h.from_scene_id == scene_id]

    def hops_into(self, scene_id: str) -> List[SceneHop]:
        return [h for h in self.hops if h.to_scene_id == scene_id]

    # ---- character refs ----
    def get_character_reference(
        self, name: str,
    ) -> Optional[CharacterReference]:
        norm = (name or "").strip().lower()
        if not norm:
            return None
        for ref in self.character_references:
            if ref.name.strip().lower() == norm:
                return ref
        return None

    def upsert_character_reference(
        self, ref: CharacterReference,
    ) -> CharacterReference:
        for i, existing in enumerate(self.character_references):
            if existing.id == ref.id:
                self.character_references[i] = ref
                return ref
        self.character_references.append(ref)
        return ref

    # ---- board management ----
    def clear_board(self) -> int:
        """Remove every scene and hop. Returns the number of scenes
        dropped. Backend preferences and character references are
        preserved so the user doesn't have to re-pick defaults after
        starting fresh.

        Sister of ``auto_arrange``: the two together cover the
        "delete all + reflow if needed" workflow the user described.
        """
        n = len(self.scenes)
        self.scenes = []
        self.hops = []
        return n

    def auto_arrange(self) -> None:
        """Re-flow every scene's grid position into a clean grid.

        Order is topological by hops when the graph is a DAG (so a
        viewer reads the storyboard in story order); falls back to
        creation order otherwise. Resets all scenes to start at
        (0, 0) and fills row-by-row across ``grid_cols``, growing
        ``grid_rows`` as needed so the auto-flowed layout always
        fits within the canvas bounds.
        """
        if not self.scenes:
            return
        ordered_ids = self._topological_or_creation_order()
        cols = max(1, self.grid_cols)
        # Walk in order, placing each scene at the next cell.
        idx_to_pos = {}
        for i, sid in enumerate(ordered_ids):
            col = i % cols
            row = i // cols
            idx_to_pos[sid] = (col, row)
        # Ensure the grid has enough rows.
        max_row = max((p[1] for p in idx_to_pos.values()), default=0)
        if max_row + 1 > self.grid_rows:
            self.grid_rows = max_row + 1
        # Apply.
        for s in self.scenes:
            pos = idx_to_pos.get(s.id)
            if pos is None:
                continue
            s.grid_col, s.grid_row = pos

    def _topological_or_creation_order(self) -> List[str]:
        """Kahn's algorithm; falls back to creation order on a cycle
        or when there are no hops."""
        if not self.hops:
            return [s.id for s in self.scenes]
        in_degree: Dict[str, int] = {s.id: 0 for s in self.scenes}
        out_edges: Dict[str, List[str]] = {s.id: [] for s in self.scenes}
        for h in self.hops:
            if (h.from_scene_id in in_degree
                    and h.to_scene_id in in_degree):
                out_edges[h.from_scene_id].append(h.to_scene_id)
                in_degree[h.to_scene_id] += 1
        # Seed the queue with scenes that have no incoming hops, in
        # creation order so ties are deterministic.
        ordered_ids = [s.id for s in self.scenes]
        queue = [sid for sid in ordered_ids
                 if in_degree.get(sid, 0) == 0]
        result: List[str] = []
        while queue:
            sid = queue.pop(0)
            result.append(sid)
            for target in out_edges.get(sid, []):
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    queue.append(target)
        # Cycle? Fall back to creation order so we don't drop scenes.
        if len(result) != len(ordered_ids):
            return ordered_ids
        return result

    # ---- stitching path ----
    def topological_order_starting_at(
        self, start_id: str,
    ) -> List[Scene]:
        """Walk outgoing hops from ``start_id`` in BFS order.

        Used by the stitcher when the user picks "stitch from here
        along the hops". Cycle-safe: visited set prevents revisits.
        """
        ordered: List[Scene] = []
        visited: set = set()
        queue: List[str] = [start_id]
        while queue:
            sid = queue.pop(0)
            if sid in visited:
                continue
            visited.add(sid)
            s = self.get_scene(sid)
            if s is None:
                continue
            ordered.append(s)
            for h in self.hops_out_of(sid):
                if h.to_scene_id not in visited:
                    queue.append(h.to_scene_id)
        return ordered
