"""Fleet Manager -- orchestrates persistent Claude Code agent instances.

Manages spawning, resuming, batching, and mediating between independent
Claude Code processes via ``claude -p --resume``.
"""

import asyncio
import contextlib
import json
import os
import re
import tempfile
import time
from typing import Callable, Awaitable

from synapsis.config import logger, WORKSPACE


def _write_system_prompt_tempfile(prompt_text: str) -> str:
    """Write a system prompt to a temp file and return its absolute path.

    Mirrors the orchestrator's --system-prompt-file mechanism in
    ``synapsis/agent_options.py``: passing a large system prompt inline via
    ``--system-prompt`` can exceed ARG_MAX (E2BIG / [Errno 7]) on Linux. Writing
    it to a file and passing ``--system-prompt-file`` avoids that ceiling. The
    caller is responsible for removing the file after the subprocess completes.
    """
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="fleet-sp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt_text)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(path)
        raise
    return path
from synapsis.database.fleet_operations import (
    create_fleet_agent, update_fleet_agent,
    update_agent_session, update_agent_status,
    create_fleet_run, update_fleet_run, save_fleet_message,
    get_fleet_agent, list_fleet_agents, save_health_snapshot,
)

SendFn = Callable[[dict], Awaitable[None]]

# Timeout for a single agent invocation (10 minutes)
_AGENT_TIMEOUT = 600


class FleetManager:
    """Manages a fleet of persistent Claude Code agent instances."""

    def __init__(self):
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------

    async def spawn_agent(
        self,
        agent_id: str,
        system_prompt: str,
        initial_task: str,
        allowed_tools: str = "Bash,Read,Write,Edit,Glob,Grep",
        send: SendFn | None = None,
    ) -> dict:
        """Spawn a single Claude Code agent via ``claude -p``.

        Captures the session_id from JSON output for future ``--resume``.
        Returns the agent's response and session_id.
        """
        # Write the system prompt to a temp file and pass --system-prompt-file
        # instead of inline --system-prompt to avoid ARG_MAX (E2BIG) on large
        # prompts. Mirrors the orchestrator mechanism in agent_options.py.
        sp_file = _write_system_prompt_tempfile(system_prompt)
        cmd = [
            "claude", "-p", initial_task,
            "--output-format", "json",
            "--allowedTools", allowed_tools,
            "--system-prompt-file", sp_file,
            "--permission-mode", "acceptEdits",
        ]

        try:
            await update_agent_status(agent_id, "running")
            if send:
                await send({"type": "agent_status", "agent_id": agent_id, "status": "running"})

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKSPACE),
            )
            self._active_processes[agent_id] = result

            try:
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(), timeout=_AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                result.kill()
                await result.wait()
                raise TimeoutError(f"Agent {agent_id} timed out after {_AGENT_TIMEOUT}s")
            finally:
                self._active_processes.pop(agent_id, None)
                with contextlib.suppress(OSError):
                    os.unlink(sp_file)

            output = stdout.decode("utf-8", errors="replace")

            # Parse JSON output to extract session_id
            try:
                response_data = json.loads(output)
                session_id = response_data.get("session_id", "")
                response_text = response_data.get("result", output)
            except json.JSONDecodeError:
                session_id = ""
                response_text = output

            if session_id:
                await update_agent_session(agent_id, session_id)

            await update_agent_status(agent_id, "idle", result=response_text[:5000])

            # Save message log
            agent = await get_fleet_agent(agent_id)
            turn = (agent.get("turn_count", 0) if agent else 0) + 1
            await save_fleet_message(agent_id, "", "user", initial_task, turn)
            await save_fleet_message(agent_id, "", "assistant", response_text[:10000], turn)
            await update_fleet_agent(agent_id, turn_count=turn, last_active=time.time())

            if send:
                await send({"type": "agent_complete", "agent_id": agent_id, "session_id": session_id})

            return {"agent_id": agent_id, "session_id": session_id, "response": response_text}

        except Exception as e:
            error_msg = str(e)
            logger.error("Fleet spawn error for agent %s: %s", agent_id, error_msg)
            await update_agent_status(agent_id, "error", error_message=error_msg)
            if send:
                await send({"type": "agent_error", "agent_id": agent_id, "error": error_msg})
            return {"agent_id": agent_id, "error": error_msg}

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    async def resume_agent(
        self,
        agent_id: str,
        message: str,
        send: SendFn | None = None,
    ) -> dict:
        """Resume an existing agent session via ``claude -p --resume <session_id>``.

        The agent remembers its full conversation history.
        """
        agent = await get_fleet_agent(agent_id)
        if not agent:
            return {"error": f"Agent {agent_id} not found"}

        session_id = agent.get("claude_session_id", "")
        if not session_id:
            return {"error": f"Agent {agent_id} has no session to resume"}

        cmd = [
            "claude", "-p", message,
            "--resume", session_id,
            "--output-format", "json",
            "--permission-mode", "acceptEdits",
        ]

        try:
            await update_agent_status(agent_id, "running")
            if send:
                await send({"type": "agent_status", "agent_id": agent_id, "status": "running"})

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKSPACE),
            )
            self._active_processes[agent_id] = result

            try:
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(), timeout=_AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                result.kill()
                await result.wait()
                raise TimeoutError(f"Agent {agent_id} resume timed out after {_AGENT_TIMEOUT}s")
            finally:
                self._active_processes.pop(agent_id, None)

            output = stdout.decode("utf-8", errors="replace")

            try:
                response_data = json.loads(output)
                new_session_id = response_data.get("session_id", session_id)
                response_text = response_data.get("result", output)
            except json.JSONDecodeError:
                new_session_id = session_id
                response_text = output

            if new_session_id != session_id:
                await update_agent_session(agent_id, new_session_id)

            turn = (agent.get("turn_count", 0)) + 1
            await save_fleet_message(agent_id, "", "user", message, turn)
            await save_fleet_message(agent_id, "", "assistant", response_text[:10000], turn)
            await update_agent_status(agent_id, "idle", result=response_text[:5000])
            await update_fleet_agent(agent_id, turn_count=turn, last_active=time.time())

            if send:
                await send({"type": "agent_complete", "agent_id": agent_id, "session_id": new_session_id})

            return {"agent_id": agent_id, "session_id": new_session_id, "response": response_text}

        except Exception as e:
            error_msg = str(e)
            logger.error("Fleet resume error for agent %s: %s", agent_id, error_msg)
            await update_agent_status(agent_id, "error", error_message=error_msg)
            if send:
                await send({"type": "agent_error", "agent_id": agent_id, "error": error_msg})
            return {"agent_id": agent_id, "error": error_msg}

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    async def run_batch(
        self,
        fleet_id: str,
        run_id: str,
        agents_and_tasks: list[dict],
        concurrency: int = 3,
        send: SendFn | None = None,
    ) -> list[dict]:
        """Run multiple agents in batches with controlled concurrency.

        Uses asyncio.Semaphore to limit parallel Claude Code processes.
        """
        sem = asyncio.Semaphore(concurrency)
        total = len(agents_and_tasks)
        completed = 0

        await update_fleet_run(
            run_id, status="running", started_at=time.time(), progress_total=total,
        )

        async def run_one(item: dict) -> dict:
            nonlocal completed
            async with sem:
                agent_id = item["agent_id"]
                task = item["task"]
                agent = await get_fleet_agent(agent_id)

                if agent and agent.get("claude_session_id"):
                    res = await self.resume_agent(agent_id, task, send=send)
                else:
                    sys_prompt = item.get(
                        "system_prompt",
                        agent.get("system_prompt", "") if agent else "",
                    )
                    res = await self.spawn_agent(agent_id, sys_prompt, task, send=send)

                completed += 1
                await update_fleet_run(run_id, progress_current=completed)
                if send:
                    await send({
                        "type": "batch_progress", "run_id": run_id,
                        "completed": completed, "total": total,
                    })
                return res

        tasks = [run_one(item) for item in agents_and_tasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                processed.append({"agent_id": agents_and_tasks[i]["agent_id"], "error": str(r)})
            else:
                processed.append(r)

        await update_fleet_run(
            run_id, status="completed", completed_at=time.time(),
            result_summary=f"Completed {completed}/{total} agents",
        )

        if send:
            await send({"type": "batch_complete", "run_id": run_id, "results_count": len(processed)})

        return processed

    # ------------------------------------------------------------------
    # Two-phase initialization
    # ------------------------------------------------------------------

    async def initialize_agent(
        self,
        fleet_id: str,
        agent_name: str,
        analysis_target: str,
        analysis_context: str,
        send: SendFn | None = None,
    ) -> dict:
        """Two-phase agent initialization: analyze content then create expert.

        Phase 1: Spawn a temporary initializer agent that analyzes the target
                 content and produces a JSON blueprint.
        Phase 2: Use the initializer's blueprint to create the expert agent
                 with a tailored system prompt, then spawn it with a brief
                 verification task.

        Returns the created expert agent's details including its blueprint.
        """
        initializer_prompt = (
            "You are an initialization specialist. Your job is to analyze the "
            "following content and create a comprehensive blueprint for an expert "
            "agent.\n\n"
            f"Target: {analysis_target}\n"
            f"Context:\n{analysis_context}\n\n"
            "Use the tools available to you (Bash, Read, Glob, Grep) to inspect "
            "the target thoroughly — read files, examine schemas, explore "
            "directory structures, run queries, whatever is needed to deeply "
            "understand this content.\n\n"
            "After your analysis, output ONLY a JSON object (no markdown fences, "
            "no extra text) with these fields:\n"
            "{\n"
            '  "system_prompt": "A comprehensive system prompt for an expert '
            "agent that will be the permanent specialist for this content. "
            "Include specific details, relationships, constraints, common "
            "patterns, and gotchas you discovered. Be thorough — this agent "
            'needs to be a true expert.",\n'
            '  "specialty": "A one-line description of what this agent '
            'specializes in",\n'
            '  "context_summary": "A 2-3 paragraph summary of key findings '
            'about this content",\n'
            '  "key_insights": ["insight1", "insight2", ...]\n'
            "}"
        )

        initializer_task = (
            f"Analyze the following target and produce a JSON blueprint.\n\n"
            f"Target: {analysis_target}\n"
            f"Context:\n{analysis_context}\n\n"
            "Use your tools to inspect the target deeply, then output the "
            "JSON blueprint as specified in your instructions."
        )

        if send:
            await send({
                "type": "init_phase",
                "agent_name": agent_name,
                "phase": "initializer",
                "message": f"Phase 1: Analyzing {analysis_target}",
            })

        # Phase 1 — run the temporary initializer agent (no DB record needed).
        # Write the system prompt to a temp file and pass --system-prompt-file
        # instead of inline --system-prompt to avoid ARG_MAX (E2BIG) on large
        # prompts. Mirrors the orchestrator mechanism in agent_options.py.
        sp_file = _write_system_prompt_tempfile(initializer_prompt)
        cmd = [
            "claude", "-p", initializer_task,
            "--output-format", "json",
            "--allowedTools", "Bash,Read,Glob,Grep",
            "--system-prompt-file", sp_file,
            "--permission-mode", "acceptEdits",
        ]

        try:
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKSPACE),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(), timeout=_AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                result.kill()
                await result.wait()
                raise TimeoutError(
                    f"Initializer for '{agent_name}' timed out after {_AGENT_TIMEOUT}s"
                )
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(sp_file)

            output = stdout.decode("utf-8", errors="replace")

            # Parse the Claude JSON envelope first
            try:
                envelope = json.loads(output)
                raw_text = envelope.get("result", output)
            except json.JSONDecodeError:
                raw_text = output

            # Extract the blueprint JSON from the initializer's response.
            # The response might contain extra text around the JSON object.
            blueprint = None
            # Try to find a JSON object in the text
            json_match = re.search(
                r'\{[^{}]*"system_prompt"[^{}]*"specialty".*?\}',
                raw_text,
                re.DOTALL,
            )
            if json_match:
                try:
                    blueprint = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            # Fallback: try brute-force brace matching from first { to last }
            if blueprint is None:
                first_brace = raw_text.find("{")
                last_brace = raw_text.rfind("}")
                if first_brace != -1 and last_brace > first_brace:
                    try:
                        blueprint = json.loads(raw_text[first_brace:last_brace + 1])
                    except json.JSONDecodeError:
                        pass

            if blueprint is None:
                logger.warning(
                    "Initializer for '%s' did not produce valid JSON; "
                    "falling back to generic blueprint",
                    agent_name,
                )
                blueprint = {
                    "system_prompt": (
                        f"You are an expert agent specializing in: {analysis_target}. "
                        f"Context: {analysis_context}"
                    ),
                    "specialty": f"Expert on {analysis_target}",
                    "context_summary": f"Initialized for {analysis_target}.",
                    "key_insights": [],
                }

        except Exception as e:
            logger.error("Phase 1 failed for '%s': %s", agent_name, e)
            if send:
                await send({
                    "type": "init_error",
                    "agent_name": agent_name,
                    "error": str(e),
                })
            return {"agent_name": agent_name, "error": str(e)}

        # Phase 2 — create the expert agent with the tailored system prompt
        if send:
            await send({
                "type": "init_phase",
                "agent_name": agent_name,
                "phase": "expert_creation",
                "message": f"Phase 2: Creating expert agent for {analysis_target}",
            })

        tailored_prompt = blueprint.get("system_prompt", "")
        specialty = blueprint.get("specialty", "")
        context_summary = blueprint.get("context_summary", "")
        key_insights = blueprint.get("key_insights", [])

        # Persist the expert agent in the fleet
        agent = await create_fleet_agent(
            fleet_id=fleet_id,
            name=agent_name,
            specialty=specialty,
            system_prompt=tailored_prompt,
        )

        agent_id = agent["agent_id"]

        # Update the agent record with the context summary
        await update_fleet_agent(agent_id, context_summary=context_summary[:5000])

        # Spawn the expert with a verification task
        verification_task = (
            f"Confirm your expertise: summarize your knowledge about "
            f"{analysis_target}. Mention the most important details, "
            f"relationships, and any gotchas a user should know about."
        )

        spawn_result = await self.spawn_agent(
            agent_id=agent_id,
            system_prompt=tailored_prompt,
            initial_task=verification_task,
            send=send,
        )

        if send:
            await send({
                "type": "init_complete",
                "agent_name": agent_name,
                "agent_id": agent_id,
                "specialty": specialty,
            })

        return {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "fleet_id": fleet_id,
            "specialty": specialty,
            "context_summary": context_summary,
            "key_insights": key_insights,
            "session_id": spawn_result.get("session_id", ""),
            "verification_response": spawn_result.get("response", "")[:2000],
            "error": spawn_result.get("error"),
        }

    async def batch_initialize(
        self,
        fleet_id: str,
        targets: list[dict],
        concurrency: int = 3,
        send: SendFn | None = None,
    ) -> list[dict]:
        """Initialize multiple expert agents from a list of targets.

        Each target dict must have: ``name``, ``target``, ``context``.
        Runs ``initialize_agent`` for each with controlled concurrency.
        """
        sem = asyncio.Semaphore(concurrency)
        total = len(targets)
        completed = 0

        async def init_one(item: dict) -> dict:
            nonlocal completed
            async with sem:
                result = await self.initialize_agent(
                    fleet_id=fleet_id,
                    agent_name=item.get("name", "Agent"),
                    analysis_target=item.get("target", ""),
                    analysis_context=item.get("context", ""),
                    send=send,
                )
                completed += 1
                if send:
                    await send({
                        "type": "batch_init_progress",
                        "fleet_id": fleet_id,
                        "completed": completed,
                        "total": total,
                    })
                return result

        tasks = [init_one(t) for t in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                processed.append({
                    "agent_name": targets[i].get("name", "?"),
                    "error": str(r),
                })
            else:
                processed.append(r)

        return processed

    # ------------------------------------------------------------------
    # Mediate
    # ------------------------------------------------------------------

    async def mediate(
        self,
        agent_a_id: str,
        agent_b_id: str,
        topic: str,
        rounds: int = 2,
        send: SendFn | None = None,
    ) -> dict:
        """Facilitate a conversation between two agents.

        The orchestrator passes context back and forth for the specified
        number of rounds.
        """
        conversation = []

        response_a = await self.resume_agent(
            agent_a_id,
            f"Topic for collaboration: {topic}\n\nPlease share your perspective and analysis.",
            send=send,
        )
        conversation.append({"agent": agent_a_id, "response": response_a.get("response", "")})

        for round_num in range(rounds):
            response_b = await self.resume_agent(
                agent_b_id,
                f"Your colleague (Agent {agent_a_id}) said:\n\n"
                f"{response_a.get('response', '')[:3000]}\n\n"
                f"Please respond with your perspective on: {topic}",
                send=send,
            )
            conversation.append({"agent": agent_b_id, "response": response_b.get("response", "")})

            if round_num < rounds - 1:
                response_a = await self.resume_agent(
                    agent_a_id,
                    f"Your colleague (Agent {agent_b_id}) responded:\n\n"
                    f"{response_b.get('response', '')[:3000]}\n\n"
                    f"Please continue the discussion on: {topic}",
                    send=send,
                )
                conversation.append({"agent": agent_a_id, "response": response_a.get("response", "")})

        return {"topic": topic, "rounds": rounds, "conversation": conversation}

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        fleet_id: str,
        message: str,
        agent_ids: list[str] | None = None,
        concurrency: int = 3,
        send: SendFn | None = None,
    ) -> list[dict]:
        """Send the same message to multiple agents (or all agents in a fleet)."""
        if agent_ids is None:
            agents = await list_fleet_agents(fleet_id)
            agent_ids = [a["agent_id"] for a in agents if a["status"] != "retired"]

        agents_and_tasks = [{"agent_id": aid, "task": message} for aid in agent_ids]

        run = await create_fleet_run(fleet_id, "broadcast", agent_ids, concurrency, message)

        return await self.run_batch(fleet_id, run["run_id"], agents_and_tasks, concurrency, send)

    # ------------------------------------------------------------------
    # System health
    # ------------------------------------------------------------------

    async def get_system_health(self) -> dict:
        """Get current system health metrics."""
        try:
            import psutil
        except ImportError:
            return {
                "error": "psutil not installed",
                "ram_total_gb": 0, "ram_available_gb": 0,
                "ram_used_pct": 0, "cpu_pct": 0,
                "active_agents": len(self._active_processes),
                "claude_processes": 0,
                "can_spawn_more": True,
                "recommended_concurrency": 2,
            }

        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)

        claude_procs = 0
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline", []) or []
                if any("claude" in str(c).lower() for c in cmdline):
                    claude_procs += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        health = {
            "ram_total_gb": round(mem.total / (1024 ** 3), 1),
            "ram_available_gb": round(mem.available / (1024 ** 3), 1),
            "ram_used_pct": mem.percent,
            "cpu_pct": cpu,
            "active_agents": len(self._active_processes),
            "claude_processes": claude_procs,
            "can_spawn_more": mem.available > 1024 * 1024 * 1024,
            "recommended_concurrency": max(1, min(4, int(mem.available / (1024 ** 3) / 1.5))),
        }

        await save_health_snapshot(
            health["ram_total_gb"], health["ram_available_gb"],
            health["ram_used_pct"], health["cpu_pct"],
            health["active_agents"], health["claude_processes"],
        )

        return health

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self):
        """Cancel all running agent processes."""
        for agent_id, proc in list(self._active_processes.items()):
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        self._active_processes.clear()
        self._cancel_events.clear()
        logger.info("Fleet manager shut down — all processes terminated")


# Module-level singleton
fleet_manager = FleetManager()
