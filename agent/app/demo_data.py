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

"""Demo Mode — .agents-cli-spec.md Example Use Case 2: "Judge clicks 'Try
Demo Mode' with zero data entry. A pre-built fictional student profile (6
colleges, partial essays, mixed recommendation status, at least one
stale/uncertain research source, overlapping essay prompts, a real
recommendation conflict) is seeded into Firestore under a demo user and the
dashboard loads populated."

Hand-authored, not agent-generated: re-running the real research/conflict/
essay-matching pipeline at seed time would be slow (real web search per
college), cost real API calls on every judge's click, and be
non-deterministic — exactly what a reliable demo can't afford. So this
module IS the "pipeline output" directly, written as fixed data — except
for the two genuinely deterministic formulas (compute_priority_score,
compute_readiness_score), which run for real here so the numbers shown are
actually consistent with the rest of the app's math, not just typed in.

`seed_demo_data(user_id)` always writes into a caller-supplied user_id — see
app/api.py's /demo/seed route for why that's always a freshly-minted id
(never a shared/reset one): concurrent judges must never see or perturb
each other's demo session, and once seeded a demo profile behaves exactly
like a real one — the student can edit requirement progress, acknowledge
conflicts, add materials, etc., same as any account.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.schemas import (
    College,
    CollegeDeadlines,
    SchoolColors,
    ConfidenceLevel,
    Conflict,
    ConflictSeverity,
    EssayMatch,
    EssayPrompt,
    MatchRecommendation,
    MaterialStatus,
    MaterialType,
    Readiness,
    ReadinessBreakdown,
    Recommendation,
    RecommendationStatus,
    RecommenderType,
    Requirement,
    RequirementStatus,
    ResearchSource,
    StudentMaterial,
    Task,
    TaskCreatedBy,
    TaskStatus,
    UserMode,
    UserProfile,
)
from app.tools import firestore_tools as ft
from app.tools.scoring import (
    compute_priority_score,
    compute_readiness_score,
    recommendations_for_college,
)

# Requirement types task_planning_agent never turns into a Task for — the
# deadline itself is context, not an action. Mirrors the real agent's
# documented behavior (app/sub_agents/task_planning_agent.py).
_NON_ACTIONABLE_TYPES = {"deadline"}


def _days(now: datetime, n: int) -> datetime:
    return now + timedelta(days=n)


_SHORT_COLLEGE_NAME = {
    "MIT": "MIT",
    "Princeton University": "Princeton",
    "Stanford University": "Stanford",
    "Rice University": "Rice",
    "University of Texas at Austin": "UT Austin",
    "Harvard University": "Harvard",
}

# Fallback 2-word "what it is" label for a requirement type, used only when
# a requirement dict doesn't set its own `short_label` — every essay/
# portfolio requirement below sets one (there's real variety worth naming:
# "Personal Statement" vs "Roommate Letter"), but recommendation/testing/
# financial_aid are the same shape everywhere a college requires them, so
# one label each covers them all.
_TYPE_DEFAULT_LABEL = {
    "essay": "Supplemental Essay",
    "recommendation": "Recommendation Letters",
    "testing": "Testing Policy",
    "financial_aid": "Financial Aid",
    "portfolio": "Arts Portfolio",
    "interview": "Interview Prep",
    "major_specific": "Major Requirement",
}

# Same fallback role as _TYPE_DEFAULT_LABEL, one level down: a ~7-word
# sentence for a requirement dict that doesn't set its own
# `task_description` — matches the cap task_planning_agent.py's
# ExtractedTask.description now enforces for real tasks, so demo and live
# data read the same way on the Tasks page.
_TYPE_DEFAULT_DESCRIPTION = {
    "essay": "Draft and polish this supplemental essay.",
    "recommendation": "Line up your teacher recommendation letters.",
    "testing": "Confirm this college's current testing policy.",
    "financial_aid": "Submit the required financial aid forms.",
    "portfolio": "Prepare and submit your arts portfolio.",
    "interview": "Prepare for your admissions interview.",
    "major_specific": "Complete this major-specific requirement.",
}


def _college_spec(now: datetime) -> list[dict]:
    """One dict per college: deadlines, requirements, and (for the essay
    ones) which StudentMaterial — if any — is a plausible reuse candidate,
    by material index into `_materials_spec()`. Two colleges deliberately
    point their "community" essay at the same material (index 1) — the
    "overlapping essay prompts" demo scenario."""
    return [
        {
            "name": "MIT",
            "deadlines": CollegeDeadlines(ea=_days(now, 74), rd=_days(now, 135)),
            "school_colors": SchoolColors(primary="#750014", secondary="#8B959E"),
            "logo_url": "https://upload.wikimedia.org/wikipedia/en/thumb/4/44/MIT_Seal.svg/330px-MIT_Seal.svg.png",
            "requirements": [
                {
                    "type": "essay",
                    "description": "Personal Statement (Common App): tell your story.",
                    "short_label": "Personal Statement",
                    "task_description": "Share your personal story in your voice.",
                    "status": RequirementStatus.NEARLY_COMPLETE,
                    "completion_percentage": 85,
                    "match_material": 0,
                    "match_score": 88,
                    "match_reasoning": "Directly addresses personal growth and identity, a close, "
                    "natural fit for MIT's open-ended framing.",
                },
                {
                    "type": "essay",
                    "description": "Why MIT: what do you hope to explore? (250-word limit)",
                    "short_label": "Exploration Essay",
                    "task_description": "Explain what draws you to MIT.",
                    "status": RequirementStatus.IN_PROGRESS,
                    "completion_percentage": 40,
                },
                {
                    "type": "essay",
                    "description": "Describe the world you come from. (250-word limit)",
                    "short_label": "Background Essay",
                    "task_description": "Describe the world and community you're from.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "recommendation",
                    "description": "2 letters: one from a math/science teacher, one from a "
                    "humanities teacher.",
                    "task_description": "Ask a STEM and a humanities teacher.",
                    "status": RequirementStatus.PLANNING,
                    "completion_percentage": 15,
                    "recommendation_count": 2,
                },
                {
                    "type": "testing",
                    "description": "SAT/ACT test-optional for this cycle, policy has shifted "
                    "year to year, worth confirming before relying on it.",
                    "task_description": "Confirm SAT or ACT scores are required.",
                    "required": False,
                    "status": RequirementStatus.NOT_STARTED,
                    "confidence": ConfidenceLevel.LOW,
                    "needs_verification": True,
                    "stale_source": True,
                },
                {
                    "type": "portfolio",
                    "description": "Optional portfolio for arts/design applicants.",
                    "task_description": "Submit an optional portfolio for arts applicants.",
                    "required": False,
                    "status": RequirementStatus.NOT_STARTED,
                },
            ],
        },
        {
            "name": "Princeton University",
            "deadlines": CollegeDeadlines(ea=_days(now, 74), rd=_days(now, 135)),
            "school_colors": SchoolColors(primary="#E77500", secondary="#000000"),
            "logo_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/Princeton_seal.svg/330px-Princeton_seal.svg.png",
            "requirements": [
                {
                    "type": "essay",
                    "description": "Your Voice: Princeton essay on your community. (250-word limit)",
                    "short_label": "Community Essay",
                    "task_description": "Describe your community in Princeton's voice prompt.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "essay",
                    "description": "Extracurricular activity essay. (150-word limit)",
                    "short_label": "Activity Essay",
                    "task_description": "Describe one extracurricular activity in detail.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "recommendation",
                    "description": "2 teacher recommendations, one from a STEM class, one from "
                    "humanities or social science.",
                    "task_description": "Get one STEM and one humanities recommendation.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                    "recommendation_count": 2,
                },
                {
                    "type": "financial_aid",
                    "description": "CSS Profile due with application.",
                    "task_description": "Submit the CSS Profile with your application.",
                    "status": RequirementStatus.NOT_STARTED,
                },
            ],
        },
        {
            "name": "Stanford University",
            "deadlines": CollegeDeadlines(ea=_days(now, 74), rd=_days(now, 139)),
            "school_colors": SchoolColors(primary="#8C1515"),
            "logo_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b5/Seal_of_Leland_Stanford_Junior_University.svg/330px-Seal_of_Leland_Stanford_Junior_University.svg.png",
            "requirements": [
                {
                    "type": "essay",
                    "description": "Short essay: what matters to you, and why? (250-word limit)",
                    "short_label": "Values Essay",
                    "task_description": "Explain briefly what matters most to you.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "essay",
                    "description": "Roommate letter. (250-word limit)",
                    "short_label": "Roommate Letter",
                    "task_description": "Write a short letter to your roommate.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "recommendation",
                    "description": "One recommendation from a core academic subject teacher, "
                    "plus one from your counselor.",
                    "task_description": "Get a teacher and counselor recommendation.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                    "recommendation_count": 2,
                },
            ],
        },
        {
            "name": "Rice University",
            "deadlines": CollegeDeadlines(ed=_days(now, 74), rd=_days(now, 138)),
            "school_colors": SchoolColors(primary="#00205B", secondary="#7C7E7F"),
            "logo_url": "https://upload.wikimedia.org/wikipedia/en/thumb/c/c7/Rice_University_seal.svg/330px-Rice_University_seal.svg.png",
            "requirements": [
                {
                    "type": "essay",
                    "description": "Why Rice? (150-word limit)",
                    "short_label": "Interest Essay",
                    "task_description": "Explain briefly why you're applying to Rice.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "essay",
                    "description": "Community essay: describe a community you belong to. "
                    "(500-word limit)",
                    "short_label": "Community Essay",
                    "task_description": "Describe a community and your role.",
                    "status": RequirementStatus.IN_PROGRESS,
                    "completion_percentage": 45,
                    "match_material": 1,
                    "match_score": 82,
                    "match_reasoning": "Strong thematic overlap, both center on the same "
                    "community and the applicant's role in it.",
                },
                {
                    "type": "essay",
                    "description": "The Rice Box (optional creative supplement).",
                    "short_label": "Creative Supplement",
                    "task_description": "Complete Rice's optional creative supplement prompt.",
                    "required": False,
                    "status": RequirementStatus.NOT_STARTED,
                },
                {
                    "type": "recommendation",
                    "description": "1 counselor recommendation + 2 academic teacher evaluations.",
                    "task_description": "Line up counselor and two teacher recommendations.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                    "recommendation_count": 3,
                },
            ],
        },
        {
            "name": "University of Texas at Austin",
            "deadlines": CollegeDeadlines(rd=_days(now, 100)),
            "school_colors": SchoolColors(primary="#BF5700", secondary="#FFFFFF"),
            # Texas is an SEC school, so the live picker sources this one
            # from logobrands.com (requirements_agent._fetch_college_logo),
            # not Wikipedia — matched here for consistency with demo data.
            "logo_url": "https://logobrands.com/cdn/shop/collections/Texas_7a475bd3-63d9-4047-8911-c66b8e8bba9c.png",
            "requirements": [
                {
                    "type": "essay",
                    "description": "Common App or ApplyTexas personal essay.",
                    "short_label": "Personal Essay",
                    "task_description": "Write your Common App or ApplyTexas essay.",
                    "status": RequirementStatus.NEARLY_COMPLETE,
                    "completion_percentage": 85,
                    "match_material": 0,
                    "match_score": 80,
                    "match_reasoning": "Same personal-growth narrative fits this open-ended "
                    "personal essay prompt well.",
                },
                {
                    "type": "essay",
                    "description": "Short answer: why your intended major? (250-word limit)",
                    "short_label": "Short Answer",
                    "task_description": "Explain why you chose your intended major.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                # UT Austin doesn't require recommendations — deliberately no
                # recommendation-type Requirement here, so the conflict/gap
                # analysis correctly excludes it.
            ],
        },
        {
            "name": "Harvard University",
            "deadlines": CollegeDeadlines(ea=_days(now, 74), rd=_days(now, 135)),
            "school_colors": SchoolColors(primary="#A51C30", secondary="#1E1E1E"),
            "logo_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cc/Harvard_University_coat_of_arms.svg/330px-Harvard_University_coat_of_arms.svg.png",
            "requirements": [
                {
                    "type": "essay",
                    "description": "Why do you want to attend Harvard? (optional)",
                    "short_label": "Interest Essay",
                    "task_description": "Optional: explain your interest in Harvard.",
                    "required": False,
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                },
                {
                    "type": "essay",
                    "description": "Optional: describe a community you belong to and your role "
                    "in it.",
                    "short_label": "Community Essay",
                    "task_description": "Optional: describe your community and role.",
                    "required": False,
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                    "match_material": 1,
                    "match_score": 75,
                    "match_reasoning": "Same community-and-role framing as Rice's prompt, a "
                    "solid starting point, though Harvard's word limit is tighter.",
                },
                {
                    "type": "recommendation",
                    "description": "2 teacher recommendations, ideally from different academic "
                    "areas.",
                    "task_description": "Get two teacher recommendations from different areas.",
                    "status": RequirementStatus.NOT_STARTED,
                    "completion_percentage": 0,
                    "recommendation_count": 2,
                },
            ],
        },
    ]


def _materials_spec() -> list[dict]:
    return [
        {
            "title": "Personal Statement Draft",
            "type": MaterialType.COMMON_APP,
            "topic": "Growing up between two languages and cultures",
            "partial_text": "I've spent my whole life translating, not just words, but "
            "worlds. At home, one language; at school, another. This essay is about "
            "what that in-between space taught me about identity and resilience.",
            "completion_percentage": 90,
            "word_count": 520,
            "themes": ["resilience", "identity", "growth"],
            "status": MaterialStatus.NEARLY_COMPLETE,
        },
        {
            "title": "Community Service Reflection",
            "type": MaterialType.SUPPLEMENTAL,
            "topic": "Two years tutoring at the neighborhood library",
            "partial_text": "Every Saturday for two years, I've tutored elementary schoolers "
            "at our neighborhood library. It started as a volunteering requirement and "
            "became the thing I look forward to most all week.",
            "completion_percentage": 60,
            "word_count": 310,
            "themes": ["community", "service", "belonging"],
            "status": MaterialStatus.IN_PROGRESS,
        },
        {
            "title": "Robotics Team, Activity Description",
            "type": MaterialType.ACTIVITY_DESCRIPTION,
            "topic": "Captaining our FIRST Robotics team through a rebuild season",
            "partial_text": "Captain, School Robotics Team (10th-12th grade). Led a full "
            "rebuild after graduating seniors took most of our technical knowledge with "
            "them; organized weekly build sessions and mentored 6 underclassmen.",
            "completion_percentage": 100,
            "word_count": 150,
            "themes": ["leadership", "STEM", "teamwork"],
            "status": MaterialStatus.COMPLETE,
        },
    ]


def _requirement_gap_recommendations(now: datetime) -> list[Recommendation]:
    """Mixed recommendation status, deliberately leaving a second recommender
    unfilled for Princeton/Stanford/Harvard — the source of the demo's
    hand-authored conflict below."""
    return [
        Recommendation(
            recommender_name="Ms. Chen (AP Physics)",
            recommender_type=RecommenderType.TEACHER_STEM,
            status=RecommendationStatus.SUBMITTED,
            college_ids=[],  # filled in by seed_demo_data with real college ids
            requested_at=_days(now, -30),
        ),
        Recommendation(
            recommender_name="Mr. Alvarez (AP Literature)",
            recommender_type=RecommenderType.TEACHER_HUMANITIES,
            status=RecommendationStatus.REQUESTED,
            college_ids=[],
            requested_at=_days(now, -10),
        ),
        Recommendation(
            recommender_name="School Counselor",
            recommender_type=RecommenderType.COUNSELOR,
            status=RecommendationStatus.NOT_REQUESTED,
            college_ids=[],
        ),
    ]


def seed_demo_data(user_id: str) -> None:
    """Writes the full demo profile for `user_id`. Idempotent in effect (not
    in mechanism) only in the sense that every doc is freshly created —
    callers are expected to pass a brand-new user_id per Demo Mode click
    (see app/api.py's /demo/seed), not to re-seed an existing one."""
    now = ft.now()

    ft.save_user_profile(
        user_id,
        UserProfile(mode=UserMode.DEMO, application_year=now.year + 1, created_at=now),
    )

    materials_spec = _materials_spec()
    material_ids = [
        ft.save_student_material(
            user_id,
            StudentMaterial(
                title=spec["title"],
                type=spec["type"],
                topic=spec["topic"],
                partial_text=spec["partial_text"],
                completion_percentage=spec["completion_percentage"],
                word_count=spec["word_count"],
                themes=spec["themes"],
                status=spec["status"],
                created_at=_days(now, -20),
                updated_at=_days(now, -2),
            ),
        )
        for spec in materials_spec
    ]

    college_ids: dict[str, str] = {}
    all_requirements: list[Requirement] = []
    short_label_by_requirement_id: dict[str, str] = {}
    task_description_by_requirement_id: dict[str, str] = {}
    college_specs = _college_spec(now)
    for i, spec in enumerate(college_specs):
        college_id = ft.save_college(
            user_id,
            College(
                name=spec["name"],
                deadlines=spec["deadlines"],
                school_colors=spec["school_colors"],
                logo_url=spec.get("logo_url"),
                # get_tracked_colleges sorts by created_at — this keeps the
                # demo's Colleges table in the same order college_specs
                # lists them, instead of an arbitrary Firestore read order.
                created_at=now - timedelta(seconds=len(college_specs) - i),
            ),
        )
        college_ids[spec["name"]] = college_id

    # Recommendations + test scores are seeded here, before the readiness
    # computation loop below, since both are now account-wide inputs
    # compute_readiness_score needs for EVERY college — not something a
    # college's own Requirement docs carry any more (see app/tools/
    # scoring.py). Attach the two identified recommenders to the colleges
    # that already have a letter in motion; Princeton/Stanford/Harvard's
    # SECOND recommender stays unidentified — that gap is what the conflict
    # below is actually about.
    recs = _requirement_gap_recommendations(now)
    recs[0].college_ids = [college_ids["MIT"], college_ids["Stanford University"]]
    recs[1].college_ids = [college_ids["Princeton University"]]
    recs[2].college_ids = [college_ids["Rice University"]]
    for rec in recs:
        rec.id = ft.save_recommendation(user_id, rec)
    ft.set_test_scores_submitted(user_id, True)

    for spec in college_specs:
        college_id = college_ids[spec["name"]]
        college_requirements: list[Requirement] = []
        for req_spec in spec["requirements"]:
            source_ids: list[str] = []
            if req_spec.get("stale_source"):
                [source_id] = ft.save_research_sources(
                    user_id,
                    [
                        ResearchSource(
                            college_id=college_id,
                            url="https://forums.example.edu/threads/testing-policy-2025",
                            title="Admissions forum thread (unofficial)",
                            date_researched=_days(now, -410),
                            official=False,
                            confidence=ConfidenceLevel.LOW,
                            excerpt="A poster claims testing became 'recommended' again, but "
                            "no admissions-office page confirms this.",
                        )
                    ],
                )
                source_ids = [source_id]
            else:
                [source_id] = ft.save_research_sources(
                    user_id,
                    [
                        ResearchSource(
                            college_id=college_id,
                            url=f"https://{spec['name'].lower().replace(' ', '').replace('.', '')}.edu/admissions",
                            title=f"{spec['name']} Admissions",
                            date_researched=_days(now, -14),
                            official=True,
                            confidence=ConfidenceLevel.HIGH,
                        )
                    ],
                )
                source_ids = [source_id]

            requirement = Requirement(
                college_id=college_id,
                type=req_spec["type"],
                description=req_spec["description"],
                required=req_spec.get("required", True),
                status=req_spec.get("status", RequirementStatus.NOT_STARTED),
                completion_percentage=req_spec.get("completion_percentage", 0),
                confidence=req_spec.get("confidence", ConfidenceLevel.HIGH),
                needs_verification=req_spec.get("needs_verification", False),
                source_ids=source_ids,
                recommendation_count=req_spec.get("recommendation_count"),
            )
            college_requirements.append(requirement)
        req_ids = ft.save_requirements(user_id, college_requirements)
        for req_spec, requirement, req_id in zip(
            spec["requirements"], college_requirements, req_ids, strict=True
        ):
            requirement.id = req_id
            if "short_label" in req_spec:
                short_label_by_requirement_id[req_id] = req_spec["short_label"]
            if "task_description" in req_spec:
                task_description_by_requirement_id[req_id] = req_spec["task_description"]
        all_requirements.extend(college_requirements)

        # Essay prompts for EVERY essay-type requirement (matching the real
        # essay_matching_pipeline's actual behavior, app/tools/
        # essay_matching.py — it categorizes and upserts a prompt for each
        # one regardless of whether anything matches it). The frontend's
        # EssayNetworkGraph only ever DISPLAYS a prompt with a real match
        # though (Milestone 16+: unmatched nodes were cluttering the map),
        # so a deliberately unmatched prompt here (no `match_material`) is
        # exactly how the demo shows off that filtering — present in
        # Firestore, invisible on the graph, same as it'd be for a real
        # hyper-specific ("other" category) prompt.
        for req_spec, requirement in zip(
            spec["requirements"], college_requirements, strict=True
        ):
            if req_spec["type"] != "essay":
                continue
            [prompt_id] = ft.save_essay_prompts(
                user_id,
                [
                    EssayPrompt(
                        college_id=college_id,
                        text=req_spec["description"].split(":", 1)[-1].strip()
                        or req_spec["description"],
                        required=req_spec.get("required", True),
                        requirement_id=requirement.id,
                    )
                ],
            )
            if "match_material" not in req_spec:
                continue
            ft.save_essay_matches(
                user_id,
                [
                    EssayMatch(
                        prompt_id=prompt_id,
                        college_id=college_id,
                        material_id=material_ids[req_spec["match_material"]],
                        match_score=req_spec["match_score"],
                        shared_themes=materials_spec[req_spec["match_material"]][
                            "themes"
                        ][:2],
                        recommendation=MatchRecommendation.ADAPT,
                        reasoning=req_spec["match_reasoning"],
                        computed_at=_days(now, -2),
                    )
                ],
            )

        # Readiness — computed for real, not typed in, so it stays honest
        # relative to the requirements/recommendations/test-scores actually
        # seeded above.
        result = compute_readiness_score(
            college_requirements,
            spec["deadlines"],
            recommendations_for_college(recs, college_id),
            test_scores_submitted=True,
            now=now,
        )
        ft.save_readiness(
            user_id,
            college_id,
            Readiness(
                score=result.score,
                breakdown=ReadinessBreakdown(
                    essays=result.essays,
                    recommendations=result.recommendations,
                    testing=result.testing,
                    deadline=result.deadline,
                ),
                explanation=result.explanation_facts,
                computed_at=now,
            ),
        )

    ft.save_conflicts(
        user_id,
        [
            Conflict(
                type="recommendation",
                college_ids=[
                    college_ids["Princeton University"],
                    college_ids["Stanford University"],
                    college_ids["Harvard University"],
                ],
                description="Princeton, Stanford, and Harvard each still need a second "
                "teacher recommendation, and their preferences differ slightly. No second "
                "recommender is identified for any of the three yet.",
                recommendation="Ask a humanities or social-science teacher who knows you "
                "well for your second letter. Paired with Ms. Chen's STEM letter, that "
                "single choice satisfies all three schools' requirements.",
                severity=ConflictSeverity.HIGH,
                related_requirement_ids=[
                    r.id
                    for r in all_requirements
                    if r.type == "recommendation"
                    and r.college_id
                    in (
                        college_ids["Princeton University"],
                        college_ids["Stanford University"],
                        college_ids["Harvard University"],
                    )
                ],
            )
        ],
    )

    # Tasks — one per actionable (non-deadline) requirement, same shape
    # task_planning_agent produces, scored with the real priority formula.
    tasks: list[Task] = []
    for requirement in all_requirements:
        if requirement.type in _NON_ACTIONABLE_TYPES:
            continue
        college = next(
            spec
            for spec in college_specs
            if college_ids[spec["name"]] == requirement.college_id
        )
        deadline = (
            requirement.deadline or college["deadlines"].ea or college["deadlines"].rd
        )
        estimated_minutes = {
            "essay": 180,
            "recommendation": 20,
            "testing": 30,
            "portfolio": 240,
            "financial_aid": 45,
        }.get(requirement.type, 60)
        status = (
            TaskStatus.DONE
            if requirement.completion_percentage >= 100
            else TaskStatus.IN_PROGRESS
            if requirement.completion_percentage > 0
            else TaskStatus.NOT_STARTED
        )
        short_college_name = _SHORT_COLLEGE_NAME.get(college["name"], college["name"])
        short_label = short_label_by_requirement_id.get(
            requirement.id, _TYPE_DEFAULT_LABEL[requirement.type]
        )
        task_description = task_description_by_requirement_id.get(
            requirement.id, _TYPE_DEFAULT_DESCRIPTION[requirement.type]
        )
        tasks.append(
            Task(
                title=f"{short_college_name} {short_label}",
                description=task_description,
                college_id=requirement.college_id,
                category=requirement.type,
                deadline=deadline,
                estimated_minutes=estimated_minutes,
                required=requirement.required,
                status=status,
                source_requirement_id=requirement.id,
                created_by=TaskCreatedBy.AGENT,
                created_at=_days(now, -5),
            )
        )
    task_ids = ft.save_tasks(user_id, tasks)
    for task, task_id in zip(tasks, task_ids, strict=True):
        college = next(
            spec
            for spec in college_specs
            if college_ids[spec["name"]] == task.college_id
        )
        breakdown = compute_priority_score(
            deadline=task.deadline,
            estimated_minutes=task.estimated_minutes,
            required=task.required,
            status=task.status.value,
            has_dependencies=False,
            category=task.category,
            now=now,
        )
        ft.update_task_priority(
            user_id, task_id, breakdown.score, breakdown.explanation_facts
        )

    # A plausible-looking Agent Activity history — two batches, matching how
    # a real student would add colleges over two sessions.
    _seed_agent_run_history(user_id, now, len(all_requirements), len(tasks))


def _seed_agent_run_history(
    user_id: str, now: datetime, requirement_count: int, task_count: int
) -> None:
    batch_1_agents = [
        ("orchestrator_agent", "Researched 5 colleges and planned tasks."),
        ("college_research_agent", "Found 14 source(s) via web search."),
        ("requirements_agent", f"Extracted {requirement_count - 3} requirement(s)."),
        ("conflict_detection_agent", "Detected 1 conflict(s)."),
        (
            "essay_matching_pipeline",
            "Structured 6 essay prompt(s), found 2 reuse match(es).",
        ),
        ("task_planning_agent", f"Planned {task_count - 3} task(s)."),
        (
            "priority_explanation_agent",
            f"Scored priority for {task_count - 3} task(s).",
        ),
        ("readiness_explanation_agent", "Scored readiness for 5 college(s)."),
    ]
    batch_2_agents = [
        ("orchestrator_agent", "Researched 1 college and planned tasks."),
        ("college_research_agent", "Found 3 source(s) via web search."),
        ("requirements_agent", "Extracted 3 requirement(s)."),
        ("task_planning_agent", "Planned 3 task(s)."),
        ("readiness_explanation_agent", "Scored readiness for 1 college(s)."),
    ]
    for batch_agents, batch_start, step_seconds in (
        (batch_1_agents, _days(now, -2), 25),
        (batch_2_agents, _days(now, -1), 20),
    ):
        pipeline_run_id = f"demo-{batch_start.date().isoformat()}"
        started = batch_start
        for agent_name, summary in batch_agents:
            ended = started + timedelta(seconds=step_seconds)
            ft.seed_agent_run(
                user_id, pipeline_run_id, agent_name, started, ended, summary
            )
            started = ended
