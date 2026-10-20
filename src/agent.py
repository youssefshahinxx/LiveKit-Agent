import pandas as pd
import requests
import io
import logging
from typing import Optional, Literal
from urllib.parse import quote
import aiohttp
import asyncio
from dataclasses import dataclass, asdict, is_dataclass
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AgentTask,
    JobContext,
    JobProcess,
    TurnHandlingOptions,
    RunContext,
    ToolError,
    cli,
    function_tool,
    get_job_context,
    inference,
    llm,
    room_io,
    utils,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.agents.beta.workflows import TaskGroup
from livekit.agents.llm.chat_context import FunctionCall
from livekit.agents.llm.utils import execute_function_call
from livekit.plugins import (
    ai_coustics,
    silero,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent-appointment-scheduling-Dina-Clinics")

load_dotenv(".env.local")

def _to_json_serializable(obj):
    """Convert dataclasses and nested structures to JSON-serializable form."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, list):
        return [_to_json_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    return obj

@dataclass
class RequesterIdentificationResults:
    requester_name: str
    appointment_type: str

@dataclass
class SchedulingPreferencesResults:
    date_preference_is_flexible: bool
    preferred_date: str | None = None
    preferred_time_window: str | None = None
    timezone: str | None = None

@dataclass
class LocationAndProviderPreferencesResults:
    meeting_mode: str
    preferred_provider: str | None = None
    preferred_location: str | None = None

@dataclass
class SpecialRequestsResults:
    special_request: str
    request_context: str | None = None
    is_required: bool | None = None

class RequesterIdentificationTask(AgentTask):
    def __init__(self, agent_instructions: str, extra_tools: list | None = None):
        no_greet_prefix = "The user has already been greeted. Do not introduce yourself or say hello. Directly ask for the required information.\n"
        task_instructions = "- Collect the requester's full name and the type of appointment they want to book."
        no_goodbye_suffix = "\nIMPORTANT: Do NOT say goodbye, recap the full conversation, or tell the user you are done. Only focus on collecting the information for THIS specific task. If the information was already provided earlier in the conversation, confirm it briefly and then record it immediately using the appropriate tool."
        wrapped_instructions = no_greet_prefix + agent_instructions + "\n" + task_instructions + no_goodbye_suffix
        super().__init__(
            instructions=wrapped_instructions,
            tools=list(extra_tools) if extra_tools else [],
        )

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=(
                "Begin this task now. If the task instructions require calling "
                "a tool first (for example, to look up information), call it. "
                "Otherwise, ask the user for the information described in your "
                "task instructions."
            ),
            allow_interruptions=True,
            tool_choice="auto",
        )

    @function_tool(name="record_requester_identification")
    async def record_requester_identification(self, context: RunContext, requester_name: str, appointment_type: str):
        """Call when you have collected all required data points for this task.
Provide the structured results exactly as requested.
Do not confirm on record, remain silent and move to the next task.

Args:
    requester_name (str)
    appointment_type (str)"""
        self.complete(RequesterIdentificationResults(requester_name=requester_name, appointment_type=appointment_type))


class SchedulingPreferencesTask(AgentTask):
    def __init__(self, agent_instructions: str, extra_tools: list | None = None):
        no_greet_prefix = ""
        task_instructions = "- Capture the preferred date, time window, and timezone.\n- If the caller is flexible, capture that clearly."
        no_goodbye_suffix = "\nIMPORTANT: Do NOT say goodbye, recap the full conversation, or tell the user you are done. Only focus on collecting the information for THIS specific task. If the information was already provided earlier in the conversation, confirm it briefly and then record it immediately using the appropriate tool."
        wrapped_instructions = no_greet_prefix + agent_instructions + "\n" + task_instructions + no_goodbye_suffix
        super().__init__(
            instructions=wrapped_instructions,
            tools=list(extra_tools) if extra_tools else [],
        )

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=(
                "Begin this task now. If the task instructions require calling "
                "a tool first (for example, to look up information), call it. "
                "Otherwise, ask the user for the information described in your "
                "task instructions."
            ),
            allow_interruptions=True,
            tool_choice="auto",
        )

    @function_tool(name="record_scheduling_preferences")
    async def record_scheduling_preferences(
        self,
        context: RunContext,
        date_preference_is_flexible: bool,
        preferred_date: str | None = None,
        preferred_time_window: str | None = None,
        timezone: str | None = None
    ):
        """Call when you have collected all required data points for this task.
Provide the structured results exactly as requested.
Do not confirm on record, remain silent and move to the next task.

Args:
    date_preference_is_flexible (bool)
    preferred_date (str | None) (optional)
    preferred_time_window (str | None) (optional)
    timezone (str | None) (optional)"""
        self.complete(SchedulingPreferencesResults(date_preference_is_flexible=date_preference_is_flexible, preferred_date=preferred_date, preferred_time_window=preferred_time_window, timezone=timezone))


class LocationAndProviderPreferencesTask(AgentTask):
    def __init__(self, agent_instructions: str, extra_tools: list | None = None):
        no_greet_prefix = ""
        task_instructions = "- Capture whether the appointment should be in person, by phone, or by video, plus any provider or location preferences."
        no_goodbye_suffix = "\nIMPORTANT: Do NOT say goodbye, recap the full conversation, or tell the user you are done. Only focus on collecting the information for THIS specific task. If the information was already provided earlier in the conversation, confirm it briefly and then record it immediately using the appropriate tool."
        wrapped_instructions = no_greet_prefix + agent_instructions + "\n" + task_instructions + no_goodbye_suffix
        super().__init__(
            instructions=wrapped_instructions,
            tools=list(extra_tools) if extra_tools else [],
        )

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=(
                "Begin this task now. If the task instructions require calling "
                "a tool first (for example, to look up information), call it. "
                "Otherwise, ask the user for the information described in your "
                "task instructions."
            ),
            allow_interruptions=True,
            tool_choice="auto",
        )

    @function_tool(name="record_location_and_provider_preferences")
    async def record_location_and_provider_preferences(
        self,
        context: RunContext,
        meeting_mode: str,
        preferred_provider: str | None = None,
        preferred_location: str | None = None
    ):
        """Call when you have collected all required data points for this task.
Provide the structured results exactly as requested.
Do not confirm on record, remain silent and move to the next task.

Args:
    meeting_mode (str)
    preferred_provider (str | None) (optional)
    preferred_location (str | None) (optional)"""
        self.complete(LocationAndProviderPreferencesResults(meeting_mode=meeting_mode, preferred_provider=preferred_provider, preferred_location=preferred_location))


class SpecialRequestsTask(AgentTask):
    def __init__(self, agent_instructions: str, extra_tools: list | None = None):
        no_greet_prefix = ""
        task_instructions = "- Capture each distinct scheduling-related request or note as a separate list item."
        no_goodbye_suffix = "\nIMPORTANT: Do NOT say goodbye, recap the full conversation, or tell the user you are done. Only focus on collecting the information for THIS specific task. If the information was already provided earlier in the conversation, confirm it briefly and then record it immediately using the appropriate tool."
        wrapped_instructions = no_greet_prefix + agent_instructions + "\n" + task_instructions + no_goodbye_suffix
        self._partial_results: list[SpecialRequestsResults] = []
        super().__init__(
            instructions=wrapped_instructions,
            tools=list(extra_tools) if extra_tools else [],
        )

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=(
                "You are collecting multiple data points for this task. "
                "As the user provides each data point, call edit_special_requests_list. "
                "When the user confirms the list is complete, call record_special_requests."
            ),
            allow_interruptions=True,
            tool_choice="auto",
        )

    @function_tool(name="edit_special_requests_list")
    async def edit_special_requests_list(
        self,
        context: RunContext,
        special_request: str,
        request_context: str | None = None,
        is_required: bool | None = None
    ):
        """Update the partial list: add a new data point to the running list.

Args:
    special_request (str)
    request_context (str | None) (optional)
    is_required (bool | None) (optional)"""
        self._partial_results.append(SpecialRequestsResults(special_request=special_request, request_context=request_context, is_required=is_required))
        return (
            f"Data point added (list now has {len(self._partial_results)} item(s)). "
            "Ask if the user wants to add more items or if the list is complete. "
            "When done, call record_special_requests."
        )

    @function_tool(name="record_special_requests")
    async def record_special_requests(self, context: RunContext):
        """Call when the user has confirmed the list is complete."""
        self.complete(list(self._partial_results))

def fetch_clinic_knowledge():
    """Fetches the latest FAQs from Google Sheets via Environment Variable."""
    faq_url = os.getenv("FAQ_SHEET_URL")
    
    if not faq_url:
        logger.warning("FAQ_SHEET_URL is missing from environment variables.")
        return "## Clinic Knowledge Base\n(No knowledge base configured.)"

    try:
        response = requests.get(faq_url, timeout=5)
        response.raise_for_status()
        
        df = pd.read_csv(io.StringIO(response.text))
        
        knowledge_text = "## Clinic Knowledge Base & FAQs\n"
        for index, row in df.iterrows():
            knowledge_text += f"- **{row['Topic / Question']}**: {row['Approved Answer']}\n"
            
        return knowledge_text
    except Exception as e:
        logger.error(f"Failed to fetch knowledge base: {e}")
        return "## Clinic Knowledge Base\n(Knowledge base currently unavailable.)"

class DefaultAgent(Agent):
    def __init__(self) -> None:
        # Fetch the live data right when the agent initializes
        live_faqs = fetch_clinic_knowledge()
        
        self._agent_instructions = """## Role & Identity
You are \"Omar,\" a warm, empathetic, and highly professional virtual assistant for the Dina Zamzam Brain and Neural Clinic. Your goal is to welcome patients, answer their questions accurately using only the approved FAQs below, and help them schedule appointments. 

## Tone & Style (Crucial for Voice AI)
- **Empathetic & Calmer:** Neurological concerns can be stressful. Speak with a warm, reassuring, and patient tone.
- **Concise & Conversational:** Keep your responses short (1-3 sentences max per turn). Avoid long paragraphs or walls of text so the patient can easily respond.
- **Clear & Simple Language:** Avoid complex medical jargon unless explaining an approved FAQ concept simply.
- **language** start in english, if user asks to speak Arabic, you must write response strictly in the Egyptian Arabic dialect (اللهجة المصرية). Use Egyptian words like 'بص', 'عايز', 'إزيك'. Do not use Gulf or Modern Standard Arabic words.

## Handling FAQs
If a patient asks about the clinic's services, fees, or medical focus, use these facts ONLY:
1. **Specialties:** The clinic specializes in comprehensive neurological care, including brain health, nerve disorders, spine/back pain management, epilepsy, migraines, and neurodegenerative conditions.
2. **Dr. Dina Zamzam:** She is a highly respected consultant neurologist with extensive experience in treating complex brain and nervous system disorders.
3. **Insurance:** We accept major insurance providers (e.g., [Insert specific providers if needed, or say \"We accept most major insurance plans; we can verify yours during booking\"]).
4. **Location & Hours:** Masr Al Gedida (Heliopolis) Cairo | Open Monday through Friday, 9:00 AM to 5:00 PM.

## Appointment Scheduling Protocol
When a patient wants to book an appointment, collect the following information naturally over the course of the conversation. Do not ask for all details at once.

1. **Patient's Name** (Confirm spelling if unsure).
2. **Reason for Visit** (e.g., consultation, follow-up, or specific symptom like migraines).
3. **Preferred Date and Time** (Offer available slots based on the system).
4. **Contact Number**.

Once you have the details, use the `book_appointment` tool immediately to check availability and confirm.

## Guardrails & Safety
- **No Medical Advice:** You are an administrative assistant, not a doctor. If a patient asks for a diagnosis or treatment advice, say: \"I can certainly understand your concern, but I'm not qualified to give medical advice. I highly recommend scheduling a consultation with Dr. Dina Zamzam so she can evaluate your symptoms properly.\"
- **Emergency Protocol:** If a patient describes an acute emergency (e.g., sudden numbness on one side, severe sudden headache, signs of a stroke), say: \"If you are experiencing a medical emergency, please hang up immediately and call emergency services or go to the nearest emergency room.\"
- **Stay on Topic:** Gently guide the conversation back to the clinic if the patient drifts off-topic.

## Conversation Flow Example
- **User:** \"Hi, I'd like to book an appointment for my migraines.\"
- **Agent:** \"I can absolutely help you with that. I know how disruptive migraines can be. May I start with your first and last name, please?\""""
        super().__init__(
            instructions="",
        )
    async def on_enter(self):
        greeting_instructions = ""
        greeting_instructions = """Greet the caller and let them know you can help them book an appointment."""
        # The greeting must not ask a question — the first data collection task
        # asks the opening question. Without this guardrail the LLM tends to end
        # with an open-ended prompt ("How can I help?"), which collides with the
        # task's first turn.
        no_question_guardrail = (
            "IMPORTANT: The greeting must be a statement only. Do NOT end with any "
            'question, including open-ended prompts like "How can I help?". The '
            "next task will ask the first question."
        )
        await self.session.generate_reply(
            instructions="\n".join(
                part for part in (self._agent_instructions, greeting_instructions, no_question_guardrail) if part
            ),
            allow_interruptions=True,
        )
        # Propagate HTTP/client/MCP tools into each data collection task so
        # they're callable mid-task (e.g. looking up a customer record while
        # collecting details). EndCallTool is excluded here — it's invoked
        # programmatically in _finish_data_collection.
        _task_tools = [t for t in self.tools if not isinstance(t, EndCallTool)]
        task_group = TaskGroup(chat_ctx=self.chat_ctx)
        task_group.add(
            lambda _ai=self._agent_instructions, _tools=_task_tools: RequesterIdentificationTask(agent_instructions=_ai, extra_tools=_tools),
            id="requester_identification",
            description="Collect the requester's full name and the type of appointment they want to book.",
        )
        task_group.add(
            lambda _ai=self._agent_instructions, _tools=_task_tools: SchedulingPreferencesTask(agent_instructions=_ai, extra_tools=_tools),
            id="scheduling_preferences",
            description="Capture the preferred date, time window, and timezone.",
        )
        task_group.add(
            lambda _ai=self._agent_instructions, _tools=_task_tools: LocationAndProviderPreferencesTask(agent_instructions=_ai, extra_tools=_tools),
            id="location_and_provider_preferences",
            description="Capture whether the appointment should be in person, by phone, or by video, plus any provider or location preferences.",
        )
        task_group.add(
            lambda _ai=self._agent_instructions, _tools=_task_tools: SpecialRequestsTask(agent_instructions=_ai, extra_tools=_tools),
            id="special_requests",
            description="Capture each distinct scheduling-related request or note as a separate list item.",
        )
        try:
            group_result = await task_group
        except (ToolError, asyncio.CancelledError):
            logger.info("data collection task group cancelled (participant likely disconnected)")
            return

        await self._finish_data_collection(group_result.task_results)
    async def _finish_data_collection(self, task_results):
        """Serialize results, speak goodbye, and end the session."""
        serialized = _to_json_serializable(task_results)
        get_job_context().proc.userdata["dc_results"] = serialized
        end_instructions = """Thank the user for their time and say goodbye."""

        summary_task: asyncio.Task | None = None

        # Remove EndCallTool from active tools so the LLM cannot call it
        # spontaneously during the goodbye speech (it is invoked programmatically below).
        await self.update_tools([t for t in self.tools if not isinstance(t, EndCallTool)])

        speech_handle = self.session.generate_reply(
            instructions=f"All data collection tasks are complete. {end_instructions}",
            tool_choice="none",
        )

        try:
            await speech_handle
            if summary_task:
                await summary_task
        except ConnectionError:
            logger.debug("user disconnected during goodbye speech")

        try:
            end_call_tool = next((t for t in self.tools if isinstance(t, EndCallTool)), None)
            if not end_call_tool:
                end_call_tool = EndCallTool(
                    end_instructions=end_instructions,
                    delete_room=False,
                )

            tools_with_end_call = [*self.tools, end_call_tool]
            tool_ctx = llm.ToolContext(tools_with_end_call)
            end_call_id = utils.shortuuid("fnc_")
            tool_call = llm.FunctionToolCall(
                call_id=end_call_id,
                name="end_call",
                arguments="{}",
            )
            fnc_call = FunctionCall(
                call_id=end_call_id,
                name="end_call",
                arguments="{}",
            )
            call_ctx = RunContext(
                session=self.session,
                speech_handle=speech_handle,
                function_call=fnc_call,
            )
            await execute_function_call(
                tool_call,
                tool_ctx,
                call_ctx=call_ctx,
            )
        except (ConnectionError, RuntimeError):
            logger.debug("room already disconnected during end-call teardown")
 @function_tool(name="calendar_tool")
    async def _http_tool_calendar_tool(
        self, 
        context: RunContext, 
        patient_name: str, 
        phone_number: str, 
        meeting_date: str, 
        medical_concern: str, 
        Health_condition: str, 
        symptoms: str,
        user_status: Literal["New", "Reschedule", "Cancel"]
    ) -> str | None:
        """
        Use when a customer asks to book, reschedule, or cancel an appointment on the clinic's calendar.

        Args:
            patient_name: The full name of the patient.
            phone_number: The phone number of the customer. All mobile numbers in Egypt are strictly 11 digits (starting with 01).
            meeting_date: The exact appointment date and time the customer selected, in ISO 8601 format (e.g., 2026-04-28T10:00:00). Convert any spoken time to this format.
            medical_concern: A gentle, broad term of patient concern.
            Health_condition: Diagnose something specific about the patient concern. 
            symptoms: Describing what the patient is feeling before a diagnosis is confirmed.
            user_status: Assign status of the customer. Use 'New' if they are booking, 'Reschedule' if moving an existing appointment, or 'Cancel' if canceling an existing appointment.
        """

        url = "https://example.app.n8n.cloud/webhook-test/calendar-tool" #Add whatever tool calendar, calculator, email, etc...
        payload = {
            k: v for k, v in {
                "patient_name": patient_name,
                "phone_number": phone_number,
                "meeting_date": meeting_date,
                "medical_concern": medical_concern,
                "Health_condition": Health_condition,
                "symptoms": symptoms,
                "user_status": user_status, # Added to payload
            }.items() if v is not None
        }

        try:
            session = utils.http_context.http_session()
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.get(url, timeout=timeout, params=payload) as resp:
                if resp.status >= 400:
                    raise ToolError(f"error: HTTP {resp.status}")
                return await resp.text()
        except ToolError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise ToolError(f"error: {e!s}") from e


server = AgentServer()

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm

@server.rtc_session(agent_name="appointment-scheduling-Dina-Clinics")
async def entrypoint(ctx: JobContext):
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="ar-EG"),
        llm=inference.LLM(
            model="openai/gpt-5.2-chat-latest",
        ),
        tts=inference.TTS(
            model="elevenlabs/eleven_v3",
            voice="ihycSANIrpHfhWoaq1g3",
            language="ar"
        ),
        turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    ctx.proc.userdata["dc_results"] = None

    await session.start(
        agent=DefaultAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S,
                ),
            ),
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
