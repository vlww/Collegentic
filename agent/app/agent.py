# ruff: noqa
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

"""Root agent entry point read by fast_api_app.py / agents-cli.

PROVISIONAL: root_agent points directly at college_research_agent so it's
independently testable before the Orchestrator exists. Milestone 5 replaces
this with orchestrator_agent, which delegates to college_research_agent as
one stage of the full intake pipeline — see .agents-cli-spec.md § Architecture.
"""

from google.adk.apps import App

from app.sub_agents.research_agent import college_research_agent

root_agent = college_research_agent

app = App(
    root_agent=root_agent,
    name="app",
)
