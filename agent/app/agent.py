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

PROVISIONAL: root_agent chains the pipeline stages built so far
(college_intake_agent -> college_research_agent -> requirements_pipeline) so
they're testable end-to-end before the Orchestrator exists. Milestone 5
replaces this with orchestrator_agent, which parses natural-language input
into `requested_colleges` and delegates to this same chain — see
.agents-cli-spec.md § Architecture.
"""

from google.adk.agents import SequentialAgent
from google.adk.apps import App

from app.sub_agents.college_intake_agent import college_intake_agent
from app.sub_agents.requirements_agent import requirements_pipeline
from app.sub_agents.research_agent import college_research_agent

root_agent = SequentialAgent(
    name="research_and_requirements_pipeline",
    sub_agents=[college_intake_agent, college_research_agent, requirements_pipeline],
)

app = App(
    root_agent=root_agent,
    name="app",
)
