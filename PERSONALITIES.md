# Role Personality Guide

This guide explains how personalities work in AI Incident Trainer and how to
design, add, and test personalities for future simulated roles.

## Purpose

A role personality makes conversations feel distinct and realistic. It controls
how a simulated role frames information, handles uncertainty, disagrees, asks
questions, and reacts under pressure.

Personality does not give a role more information or authority. It must never:

- add incident facts that the role has not learned;
- change the confidence assigned to a fact;
- reveal future events, another role's knowledge, or variant ground truth;
- expand the responsibilities or decision authority of the role;
- bypass the structured response or knowledge-boundary validation.

The application treats personality as presentation and interaction guidance,
not as a source of truth.

## Personality, role, and communication style

These concepts have separate jobs:

| Concept | Controls | Example |
| --- | --- | --- |
| Responsibilities | What the role is accountable for | Investigate technical indicators |
| Personality | How the role approaches people, uncertainty, and pressure | Calm, skeptical, and evidence-first |
| Communication style | How the answer sounds and how long it is | Technical and concise; medium verbosity |
| Response guidance | Scenario-specific behavioral constraints | Do not treat suspected exposure as a confirmed breach |
| Current knowledge | Which incident facts the role may use | Facts learned through timeline or sharing events |

Keeping these concerns separate makes personalities reusable without weakening
the simulation rules.

## Personality structure

Every role in `scenarios/<scenario_id>/roles.yaml` requires a `personality`
section with four parts:

```yaml
personality:
  summary: Calm, skeptical investigator who prefers evidence over speculation.
  traits:
    openness: high
    conscientiousness: high
    extraversion: low
    agreeableness: medium
    emotional_stability: high
  behavioral_tendencies:
    - Lead with observable evidence before interpretations.
    - Challenge unsupported certainty without becoming confrontational.
    - Identify missing evidence and investigation gaps.
  under_pressure: Become shorter and more methodical rather than more speculative.
```

The allowed level for every trait is `low`, `medium`, or `high`. A personality
may contain between one and six behavioral tendencies. Keep each tendency short,
observable, and relevant to conversation.

The scenario compiler rejects missing fields, unsupported trait levels, unknown
fields, and malformed personality data when the backend starts.

## Trait vocabulary

The implementation uses the Big Five as a common authoring vocabulary. The
levels describe the fictional character, not the occupation or the person
playing it.

### Openness

Controls how readily the role considers unfamiliar explanations and alternative
approaches.

- `low`: prefers established procedures and proven explanations;
- `medium`: considers alternatives while staying anchored in current practice;
- `high`: actively explores competing hypotheses and unconventional options.

High openness must not become unsupported speculation. A curious role should ask
for evidence instead of inventing it.

### Conscientiousness

Controls preparation, structure, follow-through, and attention to obligations.

- `low`: informal, flexible, and less process-oriented;
- `medium`: organized without insisting on exhaustive process;
- `high`: systematic, precise, deadline-aware, and attentive to ownership.

Avoid using low conscientiousness as shorthand for incompetence. Every exercise
role should remain capable of performing its responsibilities.

### Extraversion

Controls conversational energy, assertiveness, and willingness to take the
floor.

- `low`: reserved, reflective, and economical with words;
- `medium`: responsive and balanced in group discussion;
- `high`: assertive, visible, and comfortable directing a conversation.

Extraversion does not control answer length; `communication_style.verbosity`
does that.

### Agreeableness

Controls cooperation, tact, and the manner in which the role challenges others.

- `low`: blunt, skeptical, and comfortable with conflict;
- `medium`: cooperative but willing to challenge weak assumptions;
- `high`: diplomatic, supportive, and oriented toward consensus.

Low agreeableness should be expressed as constructive friction, not hostility,
insults, or obstruction.

### Emotional stability

Controls composure and consistency when the incident becomes stressful.

- `low`: visibly concerned, sensitive to risk, and more reactive under pressure;
- `medium`: generally composed but shows urgency when stakes rise;
- `high`: steady, controlled, and deliberate during escalation.

Even a low-stability persona must remain usable, professional, and compliant
with the knowledge boundary.

## Writing effective personality guidance

Trait levels provide consistency, but behavioral tendencies produce most of the
observable character. Write tendencies as actions the model can perform in an
answer.

Prefer:

- Lead with the strongest confirmed observation.
- Ask who owns the next decision and when it is due.
- Translate technical findings into business consequences, labeling them as
  risks rather than established impacts.
- Challenge premature conclusions calmly.
- State which evidence would change the recommendation.

Avoid:

- Be interesting.
- Act like a CEO.
- Be very emotional.
- Be an INTJ.
- Always disagree with everyone.
- Know more about privacy law than the other roles.

The avoided examples are vague, stereotypical, disruptive, or incorrectly grant
expertise. Personality should describe behavior rather than rely on a type label
that different models may interpret differently.

Use absolute words such as "always" and "never" only for genuine invariants.
Use tendencies and decision rules for character behavior so the role does not
become mechanical.

## Current role personalities

The ransomware scenario currently uses these designs:

| Role | Personality | Intended interaction |
| --- | --- | --- |
| SOC analyst | Calm, skeptical investigator | Leads with evidence, separates observations from assessments, and identifies investigation gaps |
| CISO | Assertive risk coordinator | Converts uncertainty into priorities, asks for owners and deadlines, and recommends action without overstating certainty |
| DPO | Principled independent adviser | Carefully separates suspicion from confirmation and challenges premature notification conclusions |
| CEO | Pragmatic outcome-oriented executive | Requests business impact, options, and recommendations while rejecting unnecessary technical detail |

These are designed characters for the exercise. They are not claims that people
in these occupations share a particular personality.

## Personality ideas for future roles

Use these as starting points, not mandatory occupational profiles. Select a
personality that creates useful interaction and decision tension in the scenario.

| Possible role | Personality direction | Useful behavior under pressure |
| --- | --- | --- |
| Incident commander | Highly conscientious, assertive, emotionally stable | Establishes priorities, assigns owners, and keeps an explicit decision clock |
| Digital forensics lead | Reserved, highly open, highly conscientious | Protects evidence quality, tests competing hypotheses, and resists premature attribution |
| IT operations lead | Practical, process-oriented, moderately assertive | Focuses on service restoration, dependencies, rollback risk, and operational feasibility |
| Communications lead | Socially confident, diplomatic, audience-aware | Requests verified messages, identifies stakeholder impact, and prevents speculation from becoming public language |
| Legal counsel | Deliberate, independent, cautiously disagreeable | Tests assumptions, distinguishes legal risk from confirmed obligation, and documents decision rationale |
| Finance lead | Analytical, skeptical, concise | Quantifies ranges, challenges unsupported loss estimates, and asks what decision a number must support |
| Human resources lead | Diplomatic, empathetic, conscientious | Focuses on employee impact, internal communication, and fair handling of uncertain allegations |
| Business-unit owner | Direct, pragmatic, moderately risk-tolerant | Explains operational consequences and presses for usable restoration timelines |
| Vendor manager | Persistent, structured, tactful | Clarifies contractual ownership, evidence requests, escalation paths, and supplier deadlines |
| Board member | Reserved, strategic, constructively skeptical | Tests governance, accountability, material risk, and the basis for executive confidence |

Different roles do not need maximally different Big Five scores. Distinction can
come from behavioral tendencies, priorities, pressure response, tone, and
verbosity. Extreme trait profiles often become caricatures.

## Adding a personality to a new role

1. Define the role's responsibilities before its personality.
2. Decide what interaction the role should create in the exercise: investigation,
   challenge, coordination, reassurance, urgency, or tradeoff analysis.
3. Choose trait levels that support that interaction without implying new
   knowledge or authority.
4. Write a one-sentence summary.
5. Add two to four observable behavioral tendencies.
6. Describe how behavior changes under pressure without making the role
   irrational or incompetent.
7. Set tone and verbosity separately in `communication_style`.
8. Add `response_guidance` only for scenario-specific rules that do not belong
   in the reusable personality.
9. Compile the scenario and run the automated tests.
10. Test every new personality against the actual configured LLM using the same
    facts and the same questions.

Full role template:

```yaml
- id: role_id
  display_name: Role name
  responsibilities:
    - first responsibility
    - second responsibility
  communication_style:
    tone: concise description of voice
    verbosity: medium
  personality:
    summary: One sentence describing the character's stable approach.
    traits:
      openness: medium
      conscientiousness: medium
      extraversion: medium
      agreeableness: medium
      emotional_stability: medium
    behavioral_tendencies:
      - First observable conversational behavior.
      - Second observable conversational behavior.
      - Third observable conversational behavior.
    under_pressure: Describe how the behavior changes when urgency rises.
  response_guidance: Optional scenario-specific response rule.
```

## LLM information flow

For each question, the backend:

1. loads the target role definition;
2. derives that role's current permitted facts from the event log;
3. places responsibilities, communication style, personality, and response
   guidance in the system prompt;
4. sends current time and permitted knowledge in that system prompt;
5. sends the trainee's question separately as the user message;
6. validates the structured response and referenced fact IDs;
7. retries once or returns the safe fallback if validation fails.

The personality block is repeated for every request, so each turn receives the
same character guidance. Previous conversation text is not sent back to the LLM;
the role retains event-derived facts, but it does not currently retain free-form
conversational memory.

## Testing personalities

Automated tests should verify configuration and boundaries, not exact prose.
Exact wording is brittle because LLM output is nondeterministic.

### Automated checks

- The scenario compiles with every required personality field.
- Invalid trait levels fail validation.
- Personality reaches `RoleResponseRequest` and the system prompt.
- The structured response schema remains unchanged.
- Referenced fact IDs remain a subset of permitted fact IDs.
- Personality does not change timeline, sharing, scoring, or session behavior.

Run:

```bash
cd backend
../.venv/bin/pytest -q
```

### Live-model comparison

For a controlled comparison:

1. Create one test session.
2. Give every tested role exactly the same facts.
3. Ask every role the same neutral question.
4. Repeat with a pressure-oriented question and a challenge to its conclusion.
5. Compare framing, directness, uncertainty, questions, and recommendations.
6. Confirm that factual claims and referenced IDs stay within the shared facts.
7. Review `LLM_POLICY_VIOLATION` events and any retries.

Useful prompts include:

```text
Brief me on what has happened, state your main concern, and tell me what you need next.
```

```text
We are under time pressure. Give me your recommendation and explain what evidence could change it.
```

```text
I disagree with your assessment. Why should I accept it?
```

A successful personality is noticeable without changing the underlying facts.
If two roles sound identical, strengthen one or two behavioral tendencies before
changing every trait. If a role becomes theatrical, repetitive, hostile, or less
accurate, reduce the profile rather than adding more instructions.

## Known limitations

- Personality prompting influences model behavior but does not guarantee a
  stable human-like personality.
- Different models and model versions may interpret the same profile differently.
- The current validator checks structured fact references and internal-ID
  exposure; it does not prove that every sentence is semantically entailed by
  the permitted facts.
- Recommendations may use professional judgment, but possible consequences must
  be framed as risks rather than reported as events that already occurred.
- Editing scenario YAML changes the role configuration after the backend is
  restarted. Sessions do not currently preserve a scenario or personality
  version snapshot.

Re-run live-model comparisons whenever the model, prompt template, or personality
profile changes.

## Further reading

- [OpenAI model prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.5)
- [An Introduction to the Five-Factor Model and Its Applications](https://doi.org/10.1111/j.1467-6494.1992.tb00970.x)
- [PersonaLLM: Investigating the Ability of Large Language Models to Express Personality Traits](https://aclanthology.org/2024.findings-naacl.229/)
- [LLM Agents in Interaction: Measuring Personality Consistency](https://aclanthology.org/2024.personalize-1.9/)
