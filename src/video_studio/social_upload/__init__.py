"""Social-platform upload backends for the Video Studio.

Each platform implements ``SocialPlatform`` (see ``base.py``) and
registers itself in ``registry.py``. The UI in
``src/ui/video_studio/social_upload_dialog.py`` walks the registry
to render the platform picker and metadata form.

Platform-specific SDKs (google-api-python-client for YouTube,
etc.) are imported lazily inside ``is_installed()`` /
``upload()`` so the rest of the studio keeps working when a
platform's optional dependency isn't installed.
"""
