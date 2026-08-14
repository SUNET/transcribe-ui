# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
#
# This file is part of Sunet Scribe.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Settings for the application.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        validate_assignment=True,
        enable_decoding=False,
    )

    API_URL: str = ""
    OIDC_APP_LOGIN_ROUTE: str = ""
    OIDC_APP_LOGOUT_ROUTE: str = ""
    OIDC_APP_REFRESH_ROUTE: str = ""
    STORAGE_SECRET: str = "change_this_secret_to_another_very_secret_secret"

    LOGO_LANDING: str = "sunet_logo.png"
    LOGO_LANDING_WIDTH: str = "250"
    LOGO_TOPBAR_LIGHT: str = "sunet_small.png"
    LOGO_TOPBAR_DARK: str = "sunet_small_dark.png"
    FAVICON: str = "favicon.ico"
    TAB_TITLE: str = "Sunet Scribe"
    TOPBAR_TEXT: str = "Sunet Scribe"
    LANDING_TEXT: str = "Welcome to Sunet Scribe"
    MANUAL_URL: str = "https://sunet.box.com/s/la16r5iu3gkm5n149mzmth9yiaulx3ub"

    # Subtitle line length guideline. Lines longer than this are flagged in
    # the editor and reported by "Validate"; nothing is truncated.
    CHARACTER_LIMIT: int = 42
    CHARACTER_LIMIT_EXCEEDED_COLOR: str = "text-red"

    # Word confidence bands, as fractions. The two thresholds cut the range
    # into three contiguous bands:
    #
    #   below 25%   Low     flagged as likely wrong
    #   25% - 75%   Medium  flagged as uncertain
    #   75% and up  High    left unmarked; the model is reliable enough that
    #                       marking it would only be noise
    #
    # Worth retuning if you change transcription models -- what counts as a
    # low score differs between them.
    CONFIDENCE_LOW: float = 0.25
    CONFIDENCE_MEDIUM: float = 0.75

    WHISPER_MODELS: list[str] = [
        "Fast transcription (normal accuracy)",
        "Slower transcription (higher accuracy)",
    ]
    WHISPER_LANGUAGES: list[str] = [
        "Swedish",
        "English",
        "Norwegian",
        "Finnish",
        "Danish",
        "French",
        "Spanish",
        "Portuguese",
        "German",
        "Italian",
        "Dutch",
        "Russian",
        "Ukrainian",
        "Icelandic",
        "Northern Sámi (Experimental)",
    ]


@lru_cache
def get_settings() -> Settings:
    """
    Get the settings for the application.
    """

    return Settings()
