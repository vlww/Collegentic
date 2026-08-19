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

root_agent is orchestrator_agent — see app/sub_agents/orchestrator_agent.py
and .agents-cli-spec.md § Orchestrator Agent. It parses which colleges a
student is applying to and delegates the actual research/extraction work to
college_intake_pipeline (college_intake_agent -> college_research_agent ->
requirements_pipeline, Milestones 3-4); it does no specialized work itself.
"""

from google.adk.apps import App

from app.sub_agents.orchestrator_agent import orchestrator_agent

root_agent = orchestrator_agent

app = App(
    root_agent=root_agent,
    name="app",
)
