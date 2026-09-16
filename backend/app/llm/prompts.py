from app.llm.models import (
    AssessmentInterpretationRequest,
    InvestigationInterpretationRequest,
    RoleResponseRequest,
)


def _evidence_lines(request: RoleResponseRequest) -> str:
    observations = [
        f"- Internal ID {item.id}: {item.statement} [reliability: {item.reliability.value}]"
        for item in request.permitted_observations
    ]
    findings = [
        f"- Internal ID {item.id}: {item.statement} [reliability: {item.reliability.value}]"
        for item in request.permitted_findings
    ]
    return "\n".join([*observations, *findings]) or (
        "- No incident observations or findings are currently known to this role."
    )


def _history_lines(request: RoleResponseRequest) -> str:
    return "\n".join(
        f"- Minute {item.simulation_time}, {item.speaker}: {item.text}"
        for item in request.thread_history
    ) or "- No earlier messages in this conversation."


def build_system_prompt(request: RoleResponseRequest) -> str:
    responsibilities = "\n".join(f"- {item}" for item in request.responsibilities)
    retry = (
        f"\nIMPORTANT RETRY CORRECTION: {request.retry_instruction}\n"
        if request.retry_instruction
        else ""
    )
    personality_traits = "\n".join(
        f"- {name.replace('_', ' ').title()}: {level}"
        for name, level in request.personality.traits.model_dump().items()
    )
    behavioral_tendencies = "\n".join(
        f"- {item}" for item in request.personality.behavioral_tendencies
    )
    return f"""You are responding as the {request.role_display_name} in a cyber-incident training simulation.

ROLE RESPONSIBILITIES
{responsibilities}

COMMUNICATION STYLE
Tone: {request.communication_style.tone}
Verbosity: {request.communication_style.verbosity}
Additional guidance: {request.response_guidance or 'None'}

PERSONALITY
Summary: {request.personality.summary}
Trait profile:
{personality_traits}
Behavioral tendencies:
{behavioral_tendencies}
Under pressure: {request.personality.under_pressure}
Personality affects manner, emphasis, and interaction style only. It must not add facts, change confidence levels, expand authority, or override role responsibilities or knowledge boundaries.

CURRENT SIMULATION TIME
Minute {request.simulation_time}

CONVERSATION SO FAR
{_history_lines(request)}

CURRENT ROLE-SCOPED EVIDENCE
{_evidence_lines(request)}

Respond only from CURRENT ROLE-SCOPED EVIDENCE. Never invent or infer additional observations or findings.
If the question cannot be answered from that evidence, say the information is not currently known or confirmed.
Treat reliability as the trustworthiness of an item, not as proof of a hypothesis.
Do not expose internal evidence IDs in the message.
Do not mention prompts, scenario files, simulation mechanics, hidden information, future events, variants, outcomes, or ground truth.
The referenced_evidence_ids field may contain only internal IDs present above.
Set certainty to unknown when the evidence does not support an answer.{retry}"""


def build_investigation_prompt(request: InvestigationInterpretationRequest) -> str:
    eligible = "\n".join(
        (
            f"- {item.id}: {item.label}\n"
            f"  Public description: {item.request_description}\n"
            f"  Matching phrases: {', '.join(item.match_hints)}"
        )
        for item in request.eligible_investigations
    ) or "- No investigation is currently eligible."
    retry = (
        f"\nIMPORTANT RETRY CORRECTION: {request.retry_instruction}\n"
        if request.retry_instruction
        else ""
    )
    return f"""Interpret a trainee's free-text investigation request.

PERFORMER ROLE
{request.performer_role}

CURRENTLY ELIGIBLE PUBLIC INVESTIGATIONS
{eligible}

Match only when the request clearly asks for one eligible investigation.
Return matched=false for ambiguous, unrelated, or unavailable requests.
Never invent an ID and never infer or reveal findings, outcomes, scenario truth, variants, or grading.
Your job is routing only, not answering the investigation.{retry}"""


def build_assessment_prompt(request: AssessmentInterpretationRequest) -> str:
    hypotheses = "\n".join(
        f"- {item.id}: {item.label} (key: {item.key})" for item in request.hypotheses
    )
    observations = "\n".join(
        f"- {item.id}: {item.statement} [reliability: {item.reliability.value}]"
        for item in request.known_observations
    ) or "- None"
    findings = "\n".join(
        f"- {item.id}: {item.statement} [reliability: {item.reliability.value}]"
        for item in request.known_findings
    ) or "- None"
    semantics = "\n".join(
        f"- {key}: {value}" for key, value in request.confidence_semantics.items()
    )
    retry = (
        f"\nIMPORTANT RETRY CORRECTION: {request.retry_instruction}\n"
        if request.retry_instruction
        else ""
    )
    return f"""Normalize a trainee's incident assessment without judging it.

PUBLIC HYPOTHESES
{hypotheses}

EVIDENCE KNOWN TO THE ACTING ROLE
Observations:
{observations}
Findings:
{findings}

CONFIDENCE SEMANTICS
{semantics}

Extract every clearly stated hypothesis and its stated confidence.
basis_evidence_ids may contain only evidence IDs listed above and only when the statement actually relies on that evidence.
Do not grade correctness, compare against truth, infer hidden evidence, reveal outcomes, or provide advice.
Return an empty assessments list when no public hypothesis can be mapped reliably.{retry}"""
