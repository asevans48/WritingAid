"""TikTok upload backend.

TikTok's Content Posting API requires a TikTok for Developers
app with the ``video.upload`` scope, the Direct Post permission,
and an OAuth grant that yields a long-lived refresh token. The
upload itself is a two-step "init then upload by chunk" flow over
HTTPS — no third-party SDK is required, just ``requests``.

This adapter handles:
  * Credential storage for client_key / client_secret / access &
    refresh tokens.
  * Refresh-on-401 so a stale access token doesn't sink an
    upload mid-flight.
  * The ``video/upload/init`` → resumable PUT → publish dance.

When the OAuth flow needs the writer's first grant, we open a
browser to TikTok's auth page; after the redirect we extract the
code from the URL the writer pastes back. Many writers find this
easier than running a local server (TikTok requires HTTPS for
redirects, which a local server can't satisfy).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .base import (
    CredentialField, Privacy, SocialPlatform, UploadRequest,
    UploadResult,
)


_TT_PRIVACY_MAP = {
    Privacy.PUBLIC: "PUBLIC_TO_EVERYONE",
    Privacy.UNLISTED: "MUTUAL_FOLLOW_FRIENDS",
    Privacy.PRIVATE: "SELF_ONLY",
}


class TikTokPlatform(SocialPlatform):
    name = "tiktok"
    label = "TikTok"
    description = (
        "Direct-post a video to a TikTok account via the Content "
        "Posting API. Requires a TikTok for Developers app with "
        "the Direct Post product enabled and the user grant for "
        "video.upload scope.")
    max_duration_seconds = 10 * 60  # 10 min for Direct Post
    aspect_hint = "9:16 vertical recommended (1080×1920)"
    credential_fields: List[CredentialField] = [
        CredentialField(
            key="client_key",
            label="App client key",
            help="From your TikTok for Developers app dashboard.",
            secret=False),
        CredentialField(
            key="client_secret",
            label="App client secret",
            secret=True),
        CredentialField(
            key="refresh_token",
            label="Refresh token (auto-populated)",
            help=(
                "Auto-populated after the first grant. Clear to "
                "force a re-auth."),
            secret=True, required=False),
        CredentialField(
            key="access_token",
            label="Access token (auto-populated)",
            secret=True, required=False),
    ]
    categories = []

    def is_installed(self) -> bool:
        try:
            import requests  # noqa: F401
            return True
        except Exception:
            return False

    def install_instructions(self) -> str:
        return (
            "TikTok uploads need the ``requests`` library "
            "(already a hard dependency of WritingAid in most "
            "installs). Install with:\n  pip install requests\n\n"
            "Then create an app at "
            "https://developers.tiktok.com/apps with the Direct "
            "Post product enabled and paste the client key + "
            "secret in the upload dialog. On first publish, the "
            "writer is taken to a TikTok URL in their browser; "
            "they grant access and paste the redirected URL "
            "back into the dialog to complete the grant.")

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------
    def auth_url(self, redirect_uri: str, state: str = "") -> str:
        """URL the writer opens in a browser to grant access. The
        dialog's "Sign in" button uses this and then asks the
        writer to paste the redirected URL back."""
        from urllib.parse import urlencode
        client_key = self.get_credential("client_key") or ""
        params = {
            "client_key": client_key,
            "scope": "video.upload",
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state or "writingaid",
        }
        return (
            "https://www.tiktok.com/v2/auth/authorize/?"
            + urlencode(params))

    def exchange_code(
        self, code: str, redirect_uri: str,
    ) -> bool:
        """Exchange the OAuth code for access + refresh tokens
        and persist them. Returns True on success."""
        try:
            import requests
        except Exception:
            return False
        client_key = self.get_credential("client_key") or ""
        client_secret = self.get_credential("client_secret") or ""
        try:
            r = requests.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": client_key,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                timeout=30)
            j = r.json()
        except Exception as e:
            print(f"[tiktok] code exchange failed: {e}")
            return False
        access = j.get("access_token", "") or ""
        refresh = j.get("refresh_token", "") or ""
        if not access:
            print(f"[tiktok] code exchange returned no access token: {j}")
            return False
        self.store_credential("access_token", access)
        if refresh:
            self.store_credential("refresh_token", refresh)
        return True

    def _refresh_access_token(self) -> bool:
        try:
            import requests
        except Exception:
            return False
        refresh = self.get_credential("refresh_token") or ""
        if not refresh:
            return False
        client_key = self.get_credential("client_key") or ""
        client_secret = self.get_credential("client_secret") or ""
        try:
            r = requests.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": client_key,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                },
                timeout=30)
            j = r.json()
        except Exception:
            return False
        access = j.get("access_token", "") or ""
        if not access:
            return False
        self.store_credential("access_token", access)
        new_refresh = j.get("refresh_token", "")
        if new_refresh:
            self.store_credential("refresh_token", new_refresh)
        return True

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
        access = self.get_credential("access_token") or ""
        if not access:
            return UploadResult(
                success=False, platform=self.name,
                error=(
                    "No access token stored. Use 'Sign in' in "
                    "the upload dialog to grant access first."))
        try:
            import requests
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"requests library unavailable: {e}")
        size_bytes = request.video_path.stat().st_size
        privacy = _TT_PRIVACY_MAP.get(
            request.metadata.privacy, "SELF_ONLY")
        # Step 1: init.
        post_info = {
            "title": (
                request.metadata.title or "Untitled")[:150],
            "privacy_level": privacy,
            "disable_comment": bool(
                request.metadata.extras.get(
                    "disable_comment", False)),
            "disable_duet": bool(
                request.metadata.extras.get(
                    "disable_duet", False)),
            "disable_stitch": bool(
                request.metadata.extras.get(
                    "disable_stitch", False)),
        }
        if request.metadata.description:
            post_info["title"] = (
                f"{post_info['title']}\n\n"
                f"{request.metadata.description}")[:2200]
        init_body = {
            "post_info": post_info,
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size_bytes,
                "chunk_size": size_bytes,
                "total_chunk_count": 1,
            },
        }
        headers = {
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        try:
            r = requests.post(
                "https://open.tiktokapis.com/v2/post/publish/"
                "video/init/",
                json=init_body, headers=headers, timeout=60)
            if r.status_code == 401:
                if self._refresh_access_token():
                    access = self.get_credential(
                        "access_token") or ""
                    headers["Authorization"] = f"Bearer {access}"
                    r = requests.post(
                        "https://open.tiktokapis.com/v2/post/"
                        "publish/video/init/",
                        json=init_body, headers=headers,
                        timeout=60)
            j = r.json()
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"init call failed: {e}")
        data = j.get("data", {}) or {}
        upload_url = data.get("upload_url", "")
        publish_id = data.get("publish_id", "")
        if not upload_url or not publish_id:
            return UploadResult(
                success=False, platform=self.name,
                error=f"TikTok init returned no upload URL: {j}",
                raw_response=j)
        # Step 2: stream the bytes to the returned URL.
        try:
            with open(request.video_path, "rb") as f:
                put_headers = {
                    "Content-Range":
                        f"bytes 0-{size_bytes - 1}/{size_bytes}",
                    "Content-Type": "video/mp4",
                }
                pr = requests.put(
                    upload_url, data=f, headers=put_headers,
                    timeout=600)
            if pr.status_code not in (200, 201, 204):
                return UploadResult(
                    success=False, platform=self.name,
                    error=(
                        "TikTok PUT failed with status "
                        f"{pr.status_code}: {pr.text[:300]}"))
        except Exception as e:
            return UploadResult(
                success=False, platform=self.name,
                error=f"video PUT failed: {e}")
        return UploadResult(
            success=True, platform=self.name,
            remote_id=publish_id,
            remote_url=(
                f"https://www.tiktok.com/@me?publish_id={publish_id}"),
            raw_response={"publish_id": publish_id})
