"""YouTube upload backend.

Implements the standard OAuth2 + resumable-upload flow:
  1. The writer pastes their Google Cloud OAuth client_id +
     client_secret in Settings (or directly in the dialog).
  2. First upload triggers ``google-auth-oauthlib``'s installed-
     app flow — opens a browser, asks the writer to grant
     YouTube upload scope, then saves the refresh token under
     the credential manager.
  3. ``upload()`` uses ``google-api-python-client`` to call
     ``videos().insert()`` with a resumable ``MediaFileUpload``.

The SDKs are optional dependencies — ``is_installed()`` returns
False with a clear hint message when they're missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .base import (
    CredentialField, Privacy, SocialPlatform, UploadRequest,
    UploadResult,
)


_YT_CATEGORIES = [
    "Film & Animation", "Autos & Vehicles", "Music",
    "Pets & Animals", "Sports", "Travel & Events", "Gaming",
    "People & Blogs", "Comedy", "Entertainment",
    "News & Politics", "How-to & Style", "Education",
    "Science & Technology", "Nonprofits & Activism",
]

# YouTube category id mapping for the most common picks.
_YT_CATEGORY_IDS = {
    "Film & Animation": "1",
    "Autos & Vehicles": "2",
    "Music": "10",
    "Pets & Animals": "15",
    "Sports": "17",
    "Travel & Events": "19",
    "Gaming": "20",
    "People & Blogs": "22",
    "Comedy": "23",
    "Entertainment": "24",
    "News & Politics": "25",
    "How-to & Style": "26",
    "Education": "27",
    "Science & Technology": "28",
    "Nonprofits & Activism": "29",
}


class YouTubePlatform(SocialPlatform):
    name = "youtube"
    label = "YouTube"
    description = (
        "Uploads to a YouTube channel via the Data API v3. "
        "Requires a Google Cloud OAuth client (Desktop app type) "
        "and the YouTube Data API enabled on the project. The "
        "first upload kicks off the browser-based grant; "
        "subsequent uploads reuse the saved refresh token.")
    max_duration_seconds = 12 * 60 * 60  # 12-hour standard cap
    aspect_hint = (
        "16:9 standard (1920×1080); 9:16 for Shorts under 60 s")
    credential_fields: List[CredentialField] = [
        CredentialField(
            key="client_id",
            label="OAuth client ID",
            help=(
                "Paste the Client ID from your Google Cloud OAuth "
                "consent / credentials page. Create a Desktop "
                "app credential type."),
            secret=False),
        CredentialField(
            key="client_secret",
            label="OAuth client secret",
            help=(
                "Paste the matching Client Secret. Stored in your "
                "system keyring; never written to disk."),
            secret=True),
        CredentialField(
            key="refresh_token",
            label="Refresh token (auto-populated)",
            help=(
                "Auto-populated after the first browser grant. "
                "Clear it to force a re-auth (e.g. when changing "
                "channels)."),
            secret=True, required=False),
    ]
    categories = list(_YT_CATEGORIES)

    def is_installed(self) -> bool:
        try:
            import google.auth  # noqa: F401
            from googleapiclient.discovery import build  # noqa: F401
            from google_auth_oauthlib.flow import (  # noqa: F401
                InstalledAppFlow)
            from google.auth.transport.requests import (  # noqa: F401
                Request)
            return True
        except Exception:
            return False

    def install_instructions(self) -> str:
        return (
            "YouTube uploads need the Google API client + OAuth "
            "library. Install them with:\n\n"
            "  pip install google-api-python-client "
            "google-auth google-auth-oauthlib\n\n"
            "Then create an OAuth client (Desktop app type) in "
            "https://console.cloud.google.com/apis/credentials "
            "with the YouTube Data API v3 enabled, paste the "
            "client ID + secret in the upload dialog, and the "
            "first upload will open a browser tab for the user "
            "grant.")

    # ------------------------------------------------------------------
    # OAuth flow
    # ------------------------------------------------------------------
    def _get_credentials(self):
        """Return google.oauth2.credentials.Credentials, kicking
        off the browser grant when no refresh_token is stored
        yet. Stores the refresh token after a successful flow."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_id = self.get_credential("client_id")
        client_secret = self.get_credential("client_secret")
        if not client_id or not client_secret:
            raise RuntimeError(
                "Missing OAuth client ID or secret. Add them in "
                "the upload dialog before publishing.")
        refresh_token = self.get_credential("refresh_token")
        if refresh_token:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=[
                    "https://www.googleapis.com/auth/youtube.upload"
                ])
            # Force a refresh so we hold a live access token.
            creds.refresh(Request())
            return creds
        # No refresh token — run the installed-app browser flow.
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri":
                    "https://accounts.google.com/o/oauth2/auth",
                "token_uri":
                    "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload"])
        creds = flow.run_local_server(
            port=0,
            prompt="consent",
            access_type="offline")
        if creds.refresh_token:
            self.store_credential(
                "refresh_token", creds.refresh_token)
        return creds

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def upload(self, request: UploadRequest) -> UploadResult:
        if not self.is_installed():
            return UploadResult(
                success=False, platform=self.name,
                error=self.install_instructions())
        if not request.video_path.exists():
            return UploadResult(
                success=False, platform=self.name,
                error=f"Video file not found: {request.video_path}")
        try:
            creds = self._get_credentials()
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"Authentication failed: {e}")
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"Google API client unavailable: {e}")
        try:
            youtube = build(
                "youtube", "v3", credentials=creds,
                cache_discovery=False)
            privacy_map = {
                Privacy.PUBLIC: "public",
                Privacy.UNLISTED: "unlisted",
                Privacy.PRIVATE: "private",
            }
            body = {
                "snippet": {
                    "title": (
                        request.metadata.title or "Untitled")[:100],
                    "description": request.metadata.description,
                    "tags": list(request.metadata.tags)[:500],
                    "categoryId": _YT_CATEGORY_IDS.get(
                        request.metadata.category, "22"),
                },
                "status": {
                    "privacyStatus": privacy_map.get(
                        request.metadata.privacy, "private"),
                    "selfDeclaredMadeForKids": False,
                },
            }
            if request.metadata.schedule_time_iso:
                body["status"]["publishAt"] = (
                    request.metadata.schedule_time_iso)
                # Scheduled uploads must start private.
                body["status"]["privacyStatus"] = "private"
            if request.metadata.language:
                body["snippet"]["defaultLanguage"] = (
                    request.metadata.language)
            media = MediaFileUpload(
                str(request.video_path.resolve()),
                chunksize=4 * 1024 * 1024,
                resumable=True)
            insert = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body, media_body=media)
            response = None
            while response is None:
                status, response = insert.next_chunk()
            vid = response.get("id", "")
            # Thumbnail upload (optional, best-effort).
            if (request.metadata.thumbnail_path
                    and Path(
                        request.metadata.thumbnail_path).exists()
                    and vid):
                try:
                    from googleapiclient.http import MediaFileUpload as _MFU
                    youtube.thumbnails().set(
                        videoId=vid,
                        media_body=_MFU(
                            str(request.metadata.thumbnail_path),
                            mimetype="image/png",
                            resumable=False)).execute()
                except Exception as e:
                    print(
                        f"[youtube] thumbnail upload failed: {e}")
            return UploadResult(
                success=True, platform=self.name,
                remote_id=vid,
                remote_url=(
                    f"https://www.youtube.com/watch?v={vid}"
                    if vid else ""),
                raw_response=response)
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"Upload failed: {e}")
