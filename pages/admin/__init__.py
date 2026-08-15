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

"""
The admin section, one module per page.

Every page other than /admin registers itself with an @ui.page decorator at
import time, so importing the submodules here is what puts those routes on
the app. /admin is registered by create(), called from main.py alongside the
other page modules.
"""

from pages.admin import (  # noqa: F401  (imported for route registration)
    analytics,
    announcements,
    customers,
    health,
    rules,
    users,
)
from pages.admin.groups import create

__all__ = ["create"]
