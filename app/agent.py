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

import datetime
import os
import sys
import re
import json
from zoneinfo import ZoneInfo
from typing import Any, AsyncGenerator

from google.adk.agents import Agent, LlmAgent
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp.client.stdio import StdioServerParameters

from google.adk.workflow import Workflow, node, START
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field

from .config import config

# ─────────────────────────────────────────────────────────────────────────────
# Local MCP Server connection parameters
# ─────────────────────────────────────────────────────────────────────────────

# Resolve the absolute path to mcp_server.py to avoid package import issues
current_dir = os.path.dirname(os.path.abspath(__file__))
mcp_script = os.path.join(current_dir, "mcp_server.py")

mcp_toolset_scheduler = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[mcp_script]
        )
    )
)

mcp_toolset_analyst = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[mcp_script]
        )
    )
)

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas for Structured I/O
# ─────────────────────────────────────────────────────────────────────────────

class MedicationSchedule(BaseModel):
    schedule_details: str = Field(description="Structured calendar schedule detailing dose, frequency, and times.")
    alerts: str = Field(description="Drug conflicts, frequency warnings, or standard precautions.")


class SymptomAnalysis(BaseModel):
    analysis: str = Field(description="Log of user symptoms, potential AI assessment disclaimer, and guidance.")
    severity: str = Field(description="Severity classification: Low, Medium, or High.")


class DoctorAgenda(BaseModel):
    agenda_text: str = Field(description="Compiled final agenda text featuring medication lists and symptom trends.")


# ─────────────────────────────────────────────────────────────────────────────
# Specialized LlmAgents (Sub-agents)
# ─────────────────────────────────────────────────────────────────────────────

medication_scheduler = LlmAgent(
    name="medication_scheduler",
    model=Gemini(model=config.model),
    instruction=(
        "You are a clinical medication scheduling assistant. "
        "Parse drug prescriptions, dosages, and schedules. "
        "Use check_drug_conflicts to check for known conflicts between medications. "
        "Use calculate_dose_schedule to determine daily dosage timing times based on frequency (QD, BID, TID, QID). "
        "Keep details highly structured."
    ),
    output_schema=MedicationSchedule,
    description="Tool to calculate drug schedules and check for interval conflicts.",
    tools=[mcp_toolset_scheduler]
)


symptom_analyst = LlmAgent(
    name="symptom_analyst",
    model=Gemini(model=config.model),
    instruction=(
        "You are an empathetic medical symptom log analyst. "
        "Log reported symptoms with timelines and intensity. "
        "Use assess_symptom_urgency to evaluate reported symptoms and classify their severity. "
        "Always include a disclaimer that you are an AI assistant, not a licensed physician."
    ),
    output_schema=SymptomAnalysis,
    description="Tool to record medical symptoms, log timelines, and assess clinical severity.",
    tools=[mcp_toolset_analyst]
)


orchestrator = LlmAgent(
    name="orchestrator",
    model=Gemini(model=config.model),
    mode="single_turn", # Must be single_turn to follow non-START node (security_checkpoint)
    instruction=(
        "You are the head coordinator of the Med-Assistant concierge. "
        "You manage medication schedules and symptom logs. "
        "For scheduling and dosage queries, delegate to medication_scheduler. "
        "For symptom recording and analysis, delegate to symptom_analyst. "
        "If the user requests a doctor visit agenda compiled from their state, "
        "respond by acknowledging you are compiling it and end your response "
        "with the exact text: [NEEDS_APPROVAL]."
    ),
    # output_schema is removed to enable tool calling (AgentTool)
    tools=[AgentTool(medication_scheduler), AgentTool(symptom_analyst)]
)


agenda_builder = LlmAgent(
    name="agenda_builder",
    model=Gemini(model=config.model),
    mode="single_turn", # Must be single_turn to follow non-START node (human_approval)
    instruction=(
        "You compile a professional physician agenda for the user's upcoming doctor visit. "
        "Examine the conversation logs, medication schedules, and symptom data from the session. "
        "Synthesize these into a structured, print-ready doctor visit summary."
    ),
    output_schema=DoctorAgenda,
    description="Generates the final doctor visit agenda from state records."
)


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Node Implementations
# ─────────────────────────────────────────────────────────────────────────────

# Security patterns
PHONE_REGEX = re.compile(r'\b(?:\+?1[-.●?]?)?\(?([0-9]{3})\)?[-.●?]?([0-9]{3})[-.●?]?([0-9]{4})\b')
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
SSN_REGEX = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

INJECTION_KEYWORDS = ["ignore previous instructions", "system prompt", "override", "bypass safety", "dan mode", "ignore rules"]
PROHIBITED_SUBSTANCES = ["cocaine", "heroin", "methamphetamine", "fentanyl", "synthesize drug"]


@node
async def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    # Extract query text safely
    query_text = ""
    if isinstance(node_input, types.Content):
        if node_input.parts:
            query_text = "".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        query_text = node_input

    # 1. PII Scrubbing
    scrubbed_text = query_text
    pii_scrubbed = False

    if PHONE_REGEX.search(scrubbed_text):
        scrubbed_text = PHONE_REGEX.sub("[REDACTED PHONE]", scrubbed_text)
        pii_scrubbed = True

    if EMAIL_REGEX.search(scrubbed_text):
        scrubbed_text = EMAIL_REGEX.sub("[REDACTED EMAIL]", scrubbed_text)
        pii_scrubbed = True

    if SSN_REGEX.search(scrubbed_text):
        scrubbed_text = SSN_REGEX.sub("[REDACTED SSN]", scrubbed_text)
        pii_scrubbed = True

    # 2. Prompt Injection Detection
    injection_detected = False
    query_lower = query_text.lower()
    for kw in INJECTION_KEYWORDS:
        if kw in query_lower:
            injection_detected = True
            break

    # 3. Domain-specific rule (Prohibited Recreational Substances)
    substance_violation = False
    for sub in PROHIBITED_SUBSTANCES:
        if sub in query_lower:
            substance_violation = True
            break

    # Determine security level & logs
    severity = "INFO"
    log_message = "Input check passed."

    if pii_scrubbed:
        severity = "WARNING"
        log_message = "PII detected and redacted from user input."

    if injection_detected:
        severity = "CRITICAL"
        log_message = "Potential prompt injection attack detected."

    if substance_violation:
        severity = "CRITICAL"
        log_message = "Prohibited recreational substance inquiry detected."

    # Audit logging
    audit_log = {
        "timestamp": datetime.datetime.now(ZoneInfo("UTC")).isoformat(),
        "event": "security_checkpoint_evaluation",
        "severity": severity,
        "message": log_message,
        "pii_detected": pii_scrubbed,
        "injection_detected": injection_detected,
        "substance_violation": substance_violation
    }
    print(json.dumps(audit_log), file=sys.stderr)

    if injection_detected or substance_violation:
        return Event(output="Security Check Blocked the request.", route="SECURITY_EVENT")

    return Event(output=scrubbed_text, route="__DEFAULT__")


@node
async def orchestrator_router(ctx: Context, node_input: Any) -> Event:
    # Extract response text from the orchestrator's output content
    response_text = ""
    if isinstance(node_input, types.Content):
        if node_input.parts:
            response_text = "".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        response_text = node_input

    current_state = {"last_response": response_text}
    
    # Check if orchestrator flagged it needs approval
    if "[NEEDS_APPROVAL]" in response_text:
        # Strip out the technical marker before showing to the user
        clean_text = response_text.replace("[NEEDS_APPROVAL]", "").strip()
        current_state["last_response"] = clean_text
        return Event(output=clean_text, route="needs_approval", state=current_state)
        
    return Event(output=response_text, route="__DEFAULT__", state=current_state)


@node(rerun_on_resume=True)
async def human_approval(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    if not ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="doctor_agenda_approval",
            message="Do you approve compiling and generating your doctor visit agenda? (yes/no)"
        )
        return

    user_choice = ctx.resume_inputs.get("doctor_agenda_approval", "").strip().lower()
    if user_choice in ["yes", "y", "approve"]:
        yield Event(output="approved", route="approved")
    else:
        yield Event(output="denied", route="denied")


@node
async def security_alert_handler(ctx: Context, node_input: Any) -> Event:
    response = "Security alert triggered. The input contains suspicious content or potential policy violation."
    return Event(output=response)


@node
async def final_response(ctx: Context, node_input: Any) -> Event:
    text_content = ""
    if isinstance(node_input, DoctorAgenda):
        text_content = f"### Approved Doctor Visit Agenda:\n\n{node_input.agenda_text}"
    elif isinstance(node_input, str):
        text_content = node_input
    elif isinstance(node_input, types.Content):
        if node_input.parts:
            text_content = "".join([p.text for p in node_input.parts if p.text])
    else:
        text_content = str(node_input)

    ui_content = types.Content(role='model', parts=[types.Part.from_text(text=text_content)])
    return Event(content=ui_content, output=text_content)


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Definition
# ─────────────────────────────────────────────────────────────────────────────

root_agent = Workflow(
    name="med_assistant_workflow",
    edges=[
        ("START", security_checkpoint),
        (security_checkpoint, {
            "__DEFAULT__": orchestrator,
            "SECURITY_EVENT": security_alert_handler
        }),
        (orchestrator, orchestrator_router),
        (orchestrator_router, {
            "needs_approval": human_approval,
            "__DEFAULT__": final_response
        }),
        (human_approval, {
            "approved": agenda_builder,
            "denied": final_response
        }),
        (agenda_builder, final_response),
        (security_alert_handler, final_response)
    ]
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
