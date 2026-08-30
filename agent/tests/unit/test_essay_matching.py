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

"""Unit tests for app/tools/essay_matching.py's deterministic categorizer
— pure functions, no Firestore, no model calls. `recompute_essay_matches`
itself (the Firestore-backed entry point) is covered live by
tests/integration/test_essay_matching_agent.py.
"""

from app.schemas import MaterialType, StudentMaterial
from app.tools.essay_matching import classify_essay_category, classify_material_category


def test_personal_statement_prompt_classified() -> None:
    assert (
        classify_essay_category(
            "Common App Essay: Personal Statement. Tell your story in 650 words."
        )
        == "personal_statement"
    )


def test_why_major_prompt_classified() -> None:
    assert (
        classify_essay_category(
            "Why are you interested in studying your intended major at our school?"
        )
        == "why_major"
    )


def test_greatest_challenge_prompt_classified() -> None:
    assert (
        classify_essay_category(
            "Describe a challenge or setback you had to overcome."
        )
        == "greatest_challenge"
    )


def test_why_major_prompt_without_the_canned_phrase_still_classified() -> None:
    """A real supplemental prompt almost never literally says "why this
    major" — this is the exact gap a real report surfaced (obviously
    why-major/personal-statement/greatest-challenge essays all landing in
    "other"). Tier 2's word-stem overlap should still catch it."""
    assert (
        classify_essay_category(
            "Please discuss the reason(s) for your selection of your first- and "
            "second-choice major(s) as indicated in the Member Section of your "
            "Common App."
        )
        == "why_major"
    )


def test_greatest_challenge_prompt_with_inflected_word_forms() -> None:
    """"struggled"/"failed" (inflected) should still hit the "struggl"/"fail"
    stems even though neither is an exact dictionary word in the list."""
    assert (
        classify_essay_category(
            "Describe a time you struggled with something difficult and how "
            "you grew from it."
        )
        == "greatest_challenge"
    )
    assert (
        classify_essay_category("Tell us about a time you failed at something.")
        == "greatest_challenge"
    )


def test_hyper_specific_prompt_falls_back_to_other() -> None:
    """The exact scenario the feature exists for: a prompt this specific to
    one school shouldn't get force-matched into any bucket."""
    assert (
        classify_essay_category(
            "If you could have any roommate, real or fictional, who would it be?"
        )
        == "other"
    )


def test_blank_prompt_is_other() -> None:
    assert classify_essay_category("") == "other"
    assert classify_essay_category(None) == "other"


def test_generic_fun_fact_prompt_still_other() -> None:
    """The leniency added for the word-stem tier shouldn't turn "other" into
    a dead bucket — genuinely generic text still has zero stem overlap with
    any category."""
    assert classify_essay_category("What is your favorite ice cream flavor and why?") == "other"


def test_common_app_material_falls_back_to_personal_statement_with_no_text_signal() -> None:
    """`type` is only a fallback — with genuinely generic text (no bucket
    keywords at all), a Common App essay still defaults to personal
    statement."""
    material = StudentMaterial(
        title="My essay",
        type=MaterialType.COMMON_APP,
        topic="Draft number three",
    )
    assert classify_material_category(material) == "personal_statement"


def test_common_app_material_text_overrides_the_type_default() -> None:
    """The actual bug this fixed: every material a student adds defaults to
    "Common App Essay" in the form regardless of topic, and Common App's
    own official personal-statement prompt OPTIONS include an "overcame a
    challenge" choice — so a CommonApp-type essay about overcoming a
    learning disability is a greatest_challenge essay in content, and
    should classify as one rather than being forced into
    personal_statement just because of its `type`."""
    material = StudentMaterial(
        title="Overcoming my learning disability",
        type=MaterialType.COMMON_APP,
        topic="How I struggled with dyslexia and overcame it through persistence",
    )
    assert classify_material_category(material) == "greatest_challenge"


def test_activity_description_material_is_always_extracurricular() -> None:
    material = StudentMaterial(title="Robotics captain", type=MaterialType.ACTIVITY_DESCRIPTION)
    assert classify_material_category(material) == "extracurricular"


def test_supplemental_material_classified_by_its_own_text() -> None:
    material = StudentMaterial(
        title="Overcoming stage fright",
        type=MaterialType.SUPPLEMENTAL,
        topic="A challenge I overcame before a debate final",
    )
    assert classify_material_category(material) == "greatest_challenge"


def test_supplemental_material_with_no_bucket_keywords_is_other() -> None:
    material = StudentMaterial(
        title="Fun facts about me",
        type=MaterialType.SUPPLEMENTAL,
        topic="Favorite snacks and a weird talent",
    )
    assert classify_material_category(material) == "other"
