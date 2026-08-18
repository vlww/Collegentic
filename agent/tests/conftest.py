# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Loads .env before pytest collects any test module.

`app/fast_api_app.py` calls `load_dotenv()` itself, but tests that import
`app.agent` directly (e.g. `tests/integration/test_agent.py`) bypass that —
without this, Vertex AI config (GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT)
is never read from `.env` and model calls fail with a misleading "No API key"
error. pytest imports conftest.py before sibling test modules, so this runs
first.
"""

from dotenv import load_dotenv

load_dotenv()
