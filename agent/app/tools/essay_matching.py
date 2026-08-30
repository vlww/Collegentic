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

"""Deterministic essay categorization + reuse matching — no LLM call.

Same "business rules in code" split as app/tools/scoring.py, applied to
essay reuse-fit: a prompt and a material either land in the same broad
category (personal statement, why-this-major, greatest challenge, ...) or
they don't — that binary bucket match is what the graph actually needs to
draw a connection, and it's instant/free to compute versus the old
LLM-judged thematic-overlap version (app/sub_agents/essay_matching_agent.py
used to be an LlmAgent; a college-research-only trigger meant a student who
just added a material via POST /api/materials saw zero connections until
their next college research run, indistinguishable from "broken" — found
live, this is why recompute_essay_matches is called directly and
synchronously from create_material/update_material in app/api.py, not just
from the pipeline).

A prompt that doesn't land in any named bucket (hyper-specific to one
school — "what would your roommate want to know about you") is "other" and
deliberately never matched to anything: forcing a same-category match for
something this specific would just be a wrong match, not a cautious one.
"""

from __future__ import annotations

import re

from app.schemas import EssayMatch, EssayPrompt, MaterialType, StudentMaterial
from app.tools import firestore_tools as ft

# Two tiers, checked in this same category order for both (a prompt hitting
# both "why this major" and "community" phrasing lands in whichever bucket
# is listed first):
#
# 1. _PHRASE_KEYWORDS — distinctive multi-word phrases. High precision:
#    finding one of these is a near-certain signal, so phrase tier always
#    wins over word tier regardless of order.
# 2. _WORD_KEYWORDS — single significant words, checked only when no phrase
#    matched anything. Real essay prompts/materials are never going to
#    literally say "why this major" — a supplemental asking a student to
#    justify "your selection of your first- and second-choice major(s)"
#    obviously belongs in why_major to a human reader, but shares zero
#    phrases with the tier-1 list above. Found live: a real report that
#    "obviously" personal-statement/why-major/greatest-challenge essays
#    weren't matching anything, all landing in "other" — phrase-only
#    matching was too strict, not the bucket-match idea itself.
#
# This deliberately trades precision for recall — "map weak connections"
# was the explicit ask — so a handful of single, fairly generic words
# appear here (e.g. "major", "attend") that a phrase-only list would never
# risk; "other" is now reserved for text sharing literally no vocabulary
# with any bucket, not just text that doesn't quote a canned phrase.
_PHRASE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "personal_statement": (
        "personal statement",
        "personal essay",
        "tell us about yourself",
        "tell your story",
        "who you are",
        "your story",
        "common app essay",
        "main essay",
        "primary essay",
    ),
    "why_school": (
        "why do you want to attend",
        "why do you want to come",
        "why us",
        "why our",
        "why here",
        "why this school",
        "why this college",
        "why this university",
        "what draws you to",
        "why you chose",
        "why are you interested in attending",
    ),
    "why_major": (
        "why this major",
        "why do you want to study",
        "why are you interested in studying",
        "academic interest",
        "intended major",
        "field of study",
        "course of study",
        "program of study",
        "area of study",
        "career goals",
        "choice of major",
        "choice of your major",
    ),
    "greatest_challenge": (
        "greatest challenge",
        "biggest challenge",
        "greatest obstacle",
        "biggest obstacle",
        "difficult time",
        "hard time",
        "tough time",
        "learned from failure",
    ),
    "community": (
        "group you belong to",
        "contribute to our campus",
        "diverse perspectives",
        "sense of belonging",
    ),
    "identity": (
        "your identity",
        "shaped who you are",
        "background has shaped",
    ),
    "extracurricular": (
        "extracurricular activity",
        "meaningful experience",
        "leadership role",
        "outside the classroom",
    ),
}

# Word STEMS, not exact words — matched by substring against each
# significant word in the text (see `_word_category_overlap`), so a single
# entry like "struggl" also catches "struggle"/"struggled"/"struggling"
# without a real stemming library. Deliberately short/generic in a few
# spots (e.g. "major", "campus") per the same leniency tradeoff as the
# module docstring — a false-positive weak match costs far less here than
# an obviously-related essay silently landing in "other".
_WORD_KEYWORDS: dict[str, frozenset[str]] = {
    "personal_statement": frozenset({"personal", "yourself", "narrat"}),
    # No "college"/"university"/"campus" here — too generic (nearly every
    # prompt mentions the school by name or type somewhere), and checked
    # before why_major in _CATEGORY_ORDER meant it was silently stealing
    # genuine why_major matches ("...that field in college" out-scored
    # "major" itself). why_school's phrase tier above already covers real
    # "why us" prompts well; this fallback stays narrow on purpose.
    "why_school": frozenset({"attend", "enroll", "matricul"}),
    "why_major": frozenset(
        {
            "major",
            "disciplin",
            "profession",
            "academic",
            "coursework",
            "curriculum",
            "studying",
        }
    ),
    "greatest_challenge": frozenset(
        {
            "challeng",
            "obstacl",
            "setback",
            "overcom",
            "overcame",  # irregular past tense — "overcom" isn't a substring of it
            "fail",
            "advers",
            "struggl",
            "hardship",
            "resilien",
            "persever",
            "difficult",
        }
    ),
    "community": frozenset({"communit", "diversit", "belong"}),
    "identity": frozenset({"identit", "heritage", "upbringing"}),
    "extracurricular": frozenset(
        {"extracurricular", "activit", "leadership", "club", "team", "sport", "hobby"}
    ),
}

_CATEGORY_ORDER = list(_PHRASE_KEYWORDS)

# A related-category match is a real but weaker signal (see baseline=45.0
# below) — without a cap, one material ends up "matching" every prompt that
# shares its related category (e.g. a single greatest_challenge essay
# winning the related slot for every personal_statement prompt across every
# tracked college, since each prompt is evaluated independently and that
# essay is the only candidate). Found live: exactly this made the essay map
# unreadable — one material fanning out to a dozen prompts it's a genuinely
# worse fit for than the ones actually kept. An essay should point at ONE
# related prompt — its best fit — not several it merely qualifies for; a
# second prompt only survives if it's a near-equally good fit (within 10%
# of the best), not just "also has some shared words". Never more than two,
# even then — three or more "equally good" related prompts starts to look
# like the old fan-out problem again.
_RELATED_MATCH_CLOSE_FRACTION = 0.9

# A handful of essay archetypes genuinely overlap in content even though
# they land in different labeled buckets — Common App's own official
# personal-statement prompt OPTIONS include a "describe a challenge you
# overcame" choice, so a prompt literally labeled "Personal Statement" and
# a material about overcoming a challenge are still a reasonable (if
# weaker) reuse candidate, not a non-match. Checked only as a fallback,
# when a prompt's own exact category has zero candidate materials — an
# exact same-category match always wins over a related one when both
# exist. Deliberately small and one-directional per pairing (declared on
# whichever category is more likely to be the prompt's label) rather than
# a fully connected graph of every category to every other.
_RELATED_CATEGORIES: dict[str, tuple[str, ...]] = {
    "personal_statement": ("greatest_challenge", "identity"),
    "why_school": ("why_major",),
    "identity": ("personal_statement", "community"),
    "community": ("identity",),
}

_CATEGORY_LABELS: dict[str, str] = {
    "personal_statement": "personal statement",
    "why_school": "why-this-school",
    "why_major": "why-this-major",
    "greatest_challenge": "greatest-challenge",
    "community": "community",
    "identity": "identity",
    "extracurricular": "extracurricular",
}

_WORD_LIMIT_RE = re.compile(r"(\d{2,4})\s*-?\s*word", re.IGNORECASE)

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "your",
        "you",
        "is",
        "are",
        "what",
        "how",
        "why",
        "that",
        "this",
        "with",
        "about",
        "from",
        "have",
        "will",
        "would",
        "that's",
        "into",
        "than",
    }
)


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in _STOPWORDS}


def _word_category_overlap(words: set[str], stems: frozenset[str]) -> int:
    """Count of `stems` present as a substring of some word in `words` —
    stand-in for real stemming (see _WORD_KEYWORDS), so "struggl" counts a
    hit against "struggled"/"struggling" without listing every inflection."""
    return sum(1 for stem in stems if any(stem in word for word in words))


def classify_essay_category(text: str | None) -> str:
    """Keyword bucket for free text (an essay prompt's description, or a
    material's own title/topic/excerpt) — "other" when nothing matches,
    which is the deliberate default for a hyper-specific prompt, not a
    failure to classify.

    Tier 1 (phrase): an exact distinctive phrase is checked first and wins
    outright. Tier 2 (word overlap): only reached when no phrase matched —
    picks whichever category shares the most significant words with the
    text, so real-world phrasing that never quotes a canned phrase still
    lands somewhere plausible instead of falling through to "other"."""
    if not text:
        return "other"
    lowered = text.lower()
    for category in _CATEGORY_ORDER:
        if any(phrase in lowered for phrase in _PHRASE_KEYWORDS[category]):
            return category

    words = _significant_words(text)
    best_category: str | None = None
    best_overlap = 0
    for category in _CATEGORY_ORDER:
        overlap = _word_category_overlap(words, _WORD_KEYWORDS[category])
        if overlap > best_overlap:
            best_category, best_overlap = category, overlap
    return best_category if best_category is not None else "other"


def classify_material_category(material: StudentMaterial) -> str:
    """Text content wins whenever it says anything specific — `type` is
    only a fallback for when it doesn't. `type` alone is a weaker signal
    than it looks: Common App's own official personal-statement prompt
    options include a "describe a challenge you overcame" choice, so a
    CommonApp-type material can genuinely be a greatest_challenge essay in
    content, not a personal_statement one. Found live: every material a
    student added defaulted to AddMaterialForm's "Common App Essay" type
    regardless of actual topic, and an earlier type-first version of this
    function forced all of them into personal_statement — an "obviously
    greatest-challenge" essay never got the chance to classify as one."""
    text = " ".join(filter(None, [material.title, material.topic, material.partial_text]))
    text_category = classify_essay_category(text)
    if text_category != "other":
        return text_category
    if material.type == MaterialType.COMMON_APP:
        return "personal_statement"
    if material.type == MaterialType.ACTIVITY_DESCRIPTION:
        return "extracurricular"
    return "other"


def _parse_word_limit(text: str) -> int | None:
    match = _WORD_LIMIT_RE.search(text)
    return int(match.group(1)) if match else None


def _match_score_and_themes(
    prompt_text: str, material_text: str, baseline: float = 60.0
) -> tuple[float, list[str]]:
    """Same-category match starts from a 60 baseline (the bucket match
    itself is a real signal) — or 45 for a related-but-not-exact category
    (see _RELATED_CATEGORIES), a deliberately weaker starting point for a
    looser connection — plus a bonus per literally shared significant
    word, capped at 95. Deliberately coarse, not fine-grained NLP scoring,
    since the whole point is a fast bucket match, not a reasoned reading
    of both texts."""
    shared = sorted(_significant_words(prompt_text) & _significant_words(material_text))
    score = min(95.0, baseline + len(shared) * 7)
    return score, shared[:5]


def recompute_essay_matches(user_id: str) -> tuple[int, int]:
    """Recategorizes every essay requirement + student material and
    rebuilds EssayPrompt/EssayMatch docs from scratch — cheap enough (pure
    Python, no network call) to run synchronously on every call site
    (app/api.py's create_material/update_material, and
    app/sub_agents/essay_matching_agent.py's pipeline stage) rather than
    only on a schedule. Upserts EssayPrompt by (requirement_id), same as the
    old LLM version did, so ids stay stable across recomputes — EssayMatch
    upserts by (prompt_id, material_id) instead of prompt_id alone, since a
    single prompt can now produce more than one match (its own category
    plus any related one — see the matching loop below).
    Returns (prompts_upserted, matches_upserted) for the caller to log.
    """
    colleges = ft.get_tracked_colleges(user_id)
    college_ids = [college.id for college in colleges]
    requirements = ft.get_requirements(user_id, college_ids)
    essay_requirements = [r for r in requirements if r.type == "essay"]
    materials = ft.get_student_materials(user_id)

    existing_prompts: list[EssayPrompt] = []
    for college_id in college_ids:
        existing_prompts.extend(ft.get_essay_prompts(user_id, college_id))
    existing_prompt_by_requirement = {
        prompt.requirement_id: prompt.id for prompt in existing_prompts if prompt.requirement_id
    }
    # Keyed by (prompt_id, material_id), not prompt_id alone — a prompt can
    # now produce more than one EssayMatch (see the matching loop below), so
    # a single prompt_id no longer uniquely identifies "the" match doc to
    # reuse the id of.
    existing_match_id_by_key = {
        (match.prompt_id, match.material_id): match.id for match in ft.get_essay_matches(user_id)
    }

    materials_by_category: dict[str, list[StudentMaterial]] = {}
    for material in materials:
        category = classify_material_category(material)
        if category == "other":
            continue
        materials_by_category.setdefault(category, []).append(material)

    prompts_to_upsert: list[EssayPrompt] = []
    category_by_requirement: dict[str, str] = {}
    for requirement in essay_requirements:
        category = classify_essay_category(requirement.description)
        category_by_requirement[requirement.id] = category
        prompts_to_upsert.append(
            EssayPrompt(
                id=existing_prompt_by_requirement.get(requirement.id),
                college_id=requirement.college_id,
                text=requirement.description,
                word_limit=_parse_word_limit(requirement.description),
                required=requirement.required,
                category=category,
                requirement_id=requirement.id,
            )
        )

    requirement_to_prompt_id: dict[str, str] = {}
    if prompts_to_upsert:
        prompt_ids = ft.save_essay_prompts(user_id, prompts_to_upsert)
        requirement_to_prompt_id = {
            prompt.requirement_id: prompt_id
            for prompt, prompt_id in zip(prompts_to_upsert, prompt_ids, strict=True)
        }

    # Collected first, filtered second (see the related-match cap below) —
    # a related-category candidate isn't turned into an EssayMatch until we
    # know how it stacks up against every other prompt the same material
    # also qualified for.
    candidates_by_key: dict[tuple[str, str], dict] = {}
    for requirement in essay_requirements:
        category = category_by_requirement[requirement.id]
        prompt_id = requirement_to_prompt_id.get(requirement.id)
        if category == "other" or prompt_id is None:
            continue

        # A prompt's own exact category AND every declared related category
        # each independently get a shot — not related-only-as-a-fallback-
        # when-exact-is-empty like before. Found live: a personal_statement
        # prompt with its own personal_statement material already matched
        # never even considered a student's separate greatest_challenge
        # material, even though Common App's own personal-statement prompt
        # OPTIONS genuinely include a "describe a challenge" choice (see
        # _RELATED_CATEGORIES' docstring) — that's a real, if weaker, reuse
        # candidate that deserves its own connection on the map, not silence
        # just because a different material already "won" the exact label.
        for match_category, is_related in (
            (category, False),
            *((related, True) for related in _RELATED_CATEGORIES.get(category, ())),
        ):
            candidates = materials_by_category.get(match_category)
            if not candidates:
                continue

            baseline = 45.0 if is_related else 60.0
            best_material: StudentMaterial | None = None
            best_score = -1.0
            best_themes: list[str] = []
            for material in candidates:
                material_text = " ".join(
                    filter(None, [material.title, material.topic, material.partial_text])
                )
                score, themes = _match_score_and_themes(
                    requirement.description, material_text, baseline
                )
                if score > best_score:
                    best_material, best_score, best_themes = material, score, themes
            if best_material is None:
                continue

            key = (prompt_id, best_material.id)
            candidates_by_key[key] = {
                "requirement": requirement,
                "prompt_id": prompt_id,
                "material": best_material,
                "score": best_score,
                "themes": best_themes,
                "category_label": _CATEGORY_LABELS.get(match_category, match_category),
                "is_related": is_related,
            }

    # An exact-category match always survives (one per prompt, that's the
    # prompt's own best-fit essay). A related-category match only survives
    # if it's that material's single best related fit — or, if a second
    # related prompt scores within _RELATED_MATCH_CLOSE_FRACTION of the
    # best, that one too (a genuine near-tie, not just "also qualifies").
    related_by_material: dict[str, list[dict]] = {}
    for candidate in candidates_by_key.values():
        if candidate["is_related"]:
            related_by_material.setdefault(candidate["material"].id, []).append(candidate)

    dropped_keys: set[tuple[str, str]] = set()
    for material_id, related_candidates in related_by_material.items():
        related_candidates.sort(key=lambda c: c["score"], reverse=True)
        best_score = related_candidates[0]["score"]
        for i, candidate in enumerate(related_candidates):
            close_second = i == 1 and candidate["score"] >= best_score * _RELATED_MATCH_CLOSE_FRACTION
            if i > 0 and not close_second:
                dropped_keys.add((candidate["prompt_id"], material_id))

    # No essay should be reused more than once *within the same college* —
    # keep only the single highest-scoring prompt for each (material,
    # college) pair, exact or related. A material can still legitimately
    # match a same-labeled prompt at several *different* colleges (that's
    # the whole point of an essay reuse map); this only rules out one essay
    # covering two different prompts for the same school.
    best_key_by_material_college: dict[tuple[str, str], tuple[str, str]] = {}
    best_score_by_material_college: dict[tuple[str, str], float] = {}
    for key, candidate in candidates_by_key.items():
        if key in dropped_keys:
            continue
        mc_key = (candidate["material"].id, candidate["requirement"].college_id)
        if (
            mc_key not in best_score_by_material_college
            or candidate["score"] > best_score_by_material_college[mc_key]
        ):
            best_score_by_material_college[mc_key] = candidate["score"]
            best_key_by_material_college[mc_key] = key
    kept_keys = set(best_key_by_material_college.values())

    # The same closeness rule applies from a *prompt's* side too, not just a
    # material's — a prompt with its own strong exact-category essay AND a
    # much weaker related-category one from a different essay (e.g. 67%
    # vs 45%) should only show the stronger connection. Only a genuine
    # near-tie (within _RELATED_MATCH_CLOSE_FRACTION) earns a prompt two
    # visible connections.
    candidates_by_prompt: dict[str, list[dict]] = {}
    for key in kept_keys:
        candidate = candidates_by_key[key]
        candidates_by_prompt.setdefault(candidate["prompt_id"], []).append(candidate)

    for prompt_id, prompt_candidates in candidates_by_prompt.items():
        prompt_candidates.sort(key=lambda c: c["score"], reverse=True)
        best_score = prompt_candidates[0]["score"]
        for i, candidate in enumerate(prompt_candidates):
            close_second = i == 1 and candidate["score"] >= best_score * _RELATED_MATCH_CLOSE_FRACTION
            if i > 0 and not close_second:
                kept_keys.discard((prompt_id, candidate["material"].id))

    matches_to_upsert: list[EssayMatch] = []
    matched_keys: set[tuple[str, str]] = set()
    for key, candidate in candidates_by_key.items():
        if key not in kept_keys:
            continue
        matched_keys.add(key)
        material = candidate["material"]
        is_related = candidate["is_related"]
        themes = candidate["themes"]
        lead_in = "Both touch on" if is_related else "Both are"
        suffix = "themes" if is_related else "essays"
        reasoning = f"{lead_in} {candidate['category_label']} {suffix}" + (
            f", sharing themes like {', '.join(themes)}." if themes else "."
        )
        score = candidate["score"]
        matches_to_upsert.append(
            EssayMatch(
                id=existing_match_id_by_key.get(key),
                prompt_id=candidate["prompt_id"],
                college_id=candidate["requirement"].college_id,
                material_id=material.id,
                match_score=score,
                shared_themes=themes,
                recommendation="adapt" if score >= 70 else "new",
                reasoning=reasoning,
                computed_at=ft.now(),
            )
        )

    if matches_to_upsert:
        ft.save_essay_matches(user_id, matches_to_upsert)

    # A (prompt, material) pairing that had a match before but doesn't this
    # pass (the material got deleted/edited out of the category, or the
    # prompt's own category changed) needs its old match doc actually
    # removed — otherwise a deleted StudentMaterial keeps "matching"
    # forever, pointing at a material_id that no longer resolves to
    # anything.
    stale_match_ids = [
        match_id for key, match_id in existing_match_id_by_key.items() if key not in matched_keys
    ]
    if stale_match_ids:
        ft.delete_essay_matches(user_id, stale_match_ids)

    return len(prompts_to_upsert), len(matches_to_upsert)
