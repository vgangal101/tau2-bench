#!/usr/bin/env python3
"""
Export simulation data to standalone HTML files for annotation.

Generates an HTML page for each simulation that includes:
- Task information (user instructions, known info, etc.)
- Tick-by-tick conversation view with tool calls
- Embedded audio player
- Interactive annotation form with localStorage persistence

Usage:
    python export_html.py --results data/simulations/my_experiment/results.json
    python export_html.py --results data/simulations/my_experiment/ --filter-reward "< 1"
    python export_html.py --results path/to/results/ --filter-tasks 9,16,31 --max-items 20
"""

import argparse
import json
import operator
import re
import shutil
from pathlib import Path
from typing import Optional

from tau2.data_model.message import ToolCall
from tau2.data_model.simulation import Results, SimulationRun
from tau2.utils.tools import to_functional_format
from tau2.utils.utils import DATA_DIR

# Constants
DEFAULT_TICK_DURATION_MS = 200
DEFAULT_DOMAIN = "retail"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> str:
    """Load a template file from the templates directory."""
    return (TEMPLATES_DIR / name).read_text()


def _escape_js_string(value: str) -> str:
    """Escape a value for safe insertion into a JS string literal."""
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("</", "<\\/")
        .replace("\n", "\\n")
    )


def format_time_ms(ms: int) -> str:
    """Format milliseconds as min:sec.ms."""
    minutes = ms // 60000
    remaining_ms = ms % 60000
    seconds = remaining_ms // 1000
    milliseconds = remaining_ms % 1000
    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


def format_tool_call(tool_call: ToolCall) -> str:
    """Format a tool call for display using compact functional notation."""
    func_str = to_functional_format(tool_call)
    return f'<div class="tool-call"><code>{escape_html(func_str)}</code></div>'


def format_tool_result(content: str, index: int) -> str:
    """Format a tool result for display."""
    try:
        result_json = json.loads(content)
        result_formatted = json.dumps(result_json, indent=2)
    except (json.JSONDecodeError, TypeError):
        result_formatted = content

    # Truncate very long results
    if len(result_formatted) > 2000:
        result_formatted = result_formatted[:2000] + "\n... (truncated)"

    return f'<details class="tool-result"><summary>Result {index}</summary><pre>{escape_html(result_formatted)}</pre></details>'


def format_tools_html(calls: list, results: list) -> str:
    """Format tool calls and results into collapsible HTML details element."""
    if not calls and not results:
        return "-"

    calls_html = "".join(format_tool_call(tc) for tc in calls)
    results_html = "".join(
        format_tool_result(tr.content, i + 1) for i, tr in enumerate(results)
    )

    # Build summary
    summary_parts = []
    if calls:
        n = len(calls)
        summary_parts.append(f"{n} call{'s' if n > 1 else ''}")
    if results:
        n = len(results)
        summary_parts.append(f"{n} result{'s' if n > 1 else ''}")

    return f"""<details class="tool-details" open>
        <summary>{", ".join(summary_parts)}</summary>
        <div class="tool-content">
            {calls_html}
            {results_html}
        </div>
    </details>"""


def generate_tick_rows(
    simulation: SimulationRun, tick_duration_ms: int = DEFAULT_TICK_DURATION_MS
) -> str:
    """Generate HTML table rows for ticks using the same grouping logic as tau2 view.

    This matches the _display_ticks_consolidated logic from display.py:
    - Empty ticks (None pattern) don't break groups
    - Tool activity always breaks a group
    - Pattern changes (based on turn-taking action) break groups
    """
    if not simulation.ticks:
        return "<tr><td colspan='6'>No tick data available</td></tr>"

    def extract_tick_info(tick) -> dict:
        """Extract info from a tick (mirrors display.py logic)."""
        info = {
            "agent_content": "",
            "agent_calls": [],
            "agent_results": [],
            "agent_turn_action": "",
            "user_content": "",
            "user_calls": [],
            "user_results": [],
            "user_turn_action": "",
        }

        if tick.agent_chunk and tick.agent_chunk.content:
            info["agent_content"] = tick.agent_chunk.content
        if tick.agent_tool_calls:
            info["agent_calls"] = tick.agent_tool_calls
        if tick.agent_tool_results:
            info["agent_results"] = tick.agent_tool_results
        if (
            tick.agent_chunk
            and hasattr(tick.agent_chunk, "turn_taking_action")
            and tick.agent_chunk.turn_taking_action
        ):
            action = tick.agent_chunk.turn_taking_action.action
            info_text = getattr(tick.agent_chunk.turn_taking_action, "info", "")
            info["agent_turn_action"] = (
                f"{action}: {info_text}" if info_text else action
            )

        if tick.user_chunk and tick.user_chunk.content:
            info["user_content"] = tick.user_chunk.content
        if tick.user_tool_calls:
            info["user_calls"] = tick.user_tool_calls
        if tick.user_tool_results:
            info["user_results"] = tick.user_tool_results
        if (
            tick.user_chunk
            and hasattr(tick.user_chunk, "turn_taking_action")
            and tick.user_chunk.turn_taking_action
        ):
            action = tick.user_chunk.turn_taking_action.action
            info_text = getattr(tick.user_chunk.turn_taking_action, "info", "")
            info["user_turn_action"] = f"{action}: {info_text}" if info_text else action

        return info

    def has_tool_activity(info: dict) -> bool:
        """Check if tick has tool calls or results."""
        return bool(
            info["agent_calls"]
            or info["agent_results"]
            or info["user_calls"]
            or info["user_results"]
        )

    def get_grouping_pattern(info: dict) -> str | None:
        """Get grouping pattern for tick (mirrors display.py logic)."""

        def normalize_action(action: str) -> str:
            action_name = action.split(":")[0].strip().lower()
            if action_name in ("generate_message", "keep_talking"):
                return "active_speech"
            return action_name

        # Check agent turn action first
        if info.get("agent_turn_action"):
            return normalize_action(info["agent_turn_action"])

        # Check user turn action
        if info.get("user_turn_action"):
            return normalize_action(info["user_turn_action"])

        # No turn action - check content
        has_agent = bool(info.get("agent_content"))
        has_user = bool(info.get("user_content"))
        if not has_agent and not has_user:
            return None  # Empty tick - can join any group

        return "active_speech"

    # Group ticks using the same logic as display.py
    groups = []
    ticks = simulation.ticks
    i = 0

    while i < len(ticks):
        tick = ticks[i]
        info = extract_tick_info(tick)
        start_tick = tick.tick_id
        group_infos = [info]

        # If this tick has tool activity, it's its own group
        if has_tool_activity(info):
            groups.append((start_tick, start_tick, group_infos))
            i += 1
            continue

        # Try to extend the group with gap-tolerant pattern matching
        last_content_pattern = get_grouping_pattern(info)
        j = i + 1

        while j < len(ticks):
            next_tick = ticks[j]
            next_info = extract_tick_info(next_tick)

            # Stop if tool activity
            if has_tool_activity(next_info):
                break

            next_pattern = get_grouping_pattern(next_info)

            # Empty ticks (None) can always join the group
            if next_pattern is None:
                group_infos.append(next_info)
                j += 1
                continue

            # If we haven't seen content yet, adopt this pattern
            if last_content_pattern is None:
                last_content_pattern = next_pattern
                group_infos.append(next_info)
                j += 1
                continue

            # Stop if pattern changes to a different non-empty pattern
            if next_pattern != last_content_pattern:
                break

            # Same pattern - continue grouping
            group_infos.append(next_info)
            j += 1

        end_tick = ticks[j - 1].tick_id
        groups.append((start_tick, end_tick, group_infos))
        i = j

    # Now render each group as a row
    rows = []
    for start_tick, end_tick, group_infos in groups:
        # Aggregate content from all ticks in group
        agent_content = "".join(info["agent_content"] for info in group_infos)
        user_content = "".join(info["user_content"] for info in group_infos)

        # Collect all tool calls/results from the group
        agent_calls = []
        agent_results = []
        user_calls = []
        user_results = []

        for info in group_infos:
            agent_calls.extend(info["agent_calls"])
            agent_results.extend(info["agent_results"])
            user_calls.extend(info["user_calls"])
            user_results.extend(info["user_results"])

        # Format tick range
        tick_range = (
            f"{start_tick}" if start_tick == end_tick else f"{start_tick}-{end_tick}"
        )
        time_str = format_time_ms(start_tick * tick_duration_ms)
        start_time_sec = (start_tick * tick_duration_ms) / 1000.0

        # Format tools
        agent_tools_html = format_tools_html(agent_calls, agent_results)
        user_tools_html = format_tools_html(user_calls, user_results)

        # Skip completely empty rows
        if not any(
            [
                agent_content,
                user_content,
                agent_calls,
                agent_results,
                user_calls,
                user_results,
            ]
        ):
            continue

        row = f'''
        <tr data-start-time="{start_time_sec}" data-tick-start="{start_tick}" data-tick-end="{end_tick}">
            <td class="tick-col" data-col="tick">
                <span class="error-marker-wrapper">
                    <span class="error-marker" data-error-ids=""></span>
                    <span class="error-tooltip"></span>
                </span>
                <span class="clickable-time" title="Click to play from here">{tick_range}</span>
            </td>
            <td class="time-col clickable-time" data-col="time" title="Click to play from here">{time_str}</td>
            <td class="agent-col" data-col="agent-speech">{escape_html(agent_content) if agent_content else '<span class="empty">—</span>'}</td>
            <td class="tool-col" data-col="agent-tools">{agent_tools_html}</td>
            <td class="user-col" data-col="user-speech">{escape_html(user_content) if user_content else '<span class="empty">—</span>'}</td>
            <td class="tool-col" data-col="user-tools">{user_tools_html}</td>
        </tr>
        '''
        rows.append(row)

    return "\n".join(rows)


def generate_html(
    simulation: SimulationRun,
    task: Optional[dict],
    audio_path: Optional[str],
    audio_filename: str = "audio.wav",
    domain: str = DEFAULT_DOMAIN,
    policy: Optional[str] = None,
    guidelines: Optional[str] = None,
    batch_name: str = "",
    experiment_label: str = "",
) -> str:
    """Generate a standalone HTML page for annotation."""

    # Task info section
    task_html = ""
    if task:
        user_scenario = task.get("user_scenario", {})
        instructions = user_scenario.get("instructions", {})

        if isinstance(instructions, dict):
            task_html = f"""
            <div class="section task-section">
                <h2>User Task (What the simulated user is trying to accomplish)</h2>
                <table class="info-table">
                    <tr><th>Domain</th><td>{escape_html(domain)}</td></tr>
                    <tr><th>Reason for Call</th><td>{escape_html(instructions.get("reason_for_call", "N/A"))}</td></tr>
                    <tr><th>Known Info</th><td><pre class="info-pre">{escape_html(instructions.get("known_info", "N/A"))}</pre></td></tr>
                    <tr><th>Unknown Info</th><td><pre class="info-pre">{escape_html(instructions.get("unknown_info", "N/A"))}</pre></td></tr>
                    <tr><th>Task Instructions</th><td><pre class="info-pre">{escape_html(instructions.get("task_instructions", "N/A"))}</pre></td></tr>
                </table>
            </div>
            """
        else:
            task_html = f"""
            <div class="section task-section">
                <h2>User Task</h2>
                <pre>{escape_html(str(instructions))}</pre>
            </div>
            """

    # Policy section (collapsible)
    policy_html = ""
    if policy:
        policy_html = f"""
        <div class="section policy-section">
            <details>
                <summary><h2 style="display: inline; cursor: pointer;">Agent Policy (Rules the agent must follow) ▶</h2></summary>
                <div class="policy-content">
                    <pre class="policy-pre">{escape_html(policy)}</pre>
                </div>
            </details>
        </div>
        """

    # Evaluation criteria
    eval_html = ""
    if task and task.get("evaluation_criteria"):
        eval_criteria = task["evaluation_criteria"]
        actions = eval_criteria.get("actions", [])
        if actions:
            actions_html = "<ul class='action-list'>"
            for action in actions:
                # Use functional format for consistency
                tc = ToolCall(
                    name=action.get("name", "unknown"),
                    arguments=action.get("arguments", {}),
                )
                func_str = to_functional_format(tc)
                actions_html += f"<li><code>{escape_html(func_str)}</code></li>"
            actions_html += "</ul>"
            eval_html = f"""
            <div class="section eval-section">
                <h2>Expected Actions (What the agent should do to succeed)</h2>
                {actions_html}
            </div>
            """

    # Simulation metadata
    reward = simulation.reward_info.reward if simulation.reward_info else "N/A"
    reward_class = (
        "success"
        if simulation.reward_info and simulation.reward_info.reward > 0
        else "failure"
    )

    meta_html = f"""
    <div class="section">
        <h2>Simulation Info</h2>
        <table class="info-table">
            <tr><th>Experiment</th><td>{escape_html(experiment_label)}</td></tr>
            <tr><th>Task ID</th><td>{simulation.task_id}</td></tr>
            <tr><th>Simulation ID</th><td><code>{simulation.id}</code></td></tr>
            <tr><th>Trial</th><td>{simulation.trial}</td></tr>
            <tr><th>Duration</th><td>{simulation.duration:.2f}s</td></tr>
            <tr><th>Termination</th><td>{simulation.termination_reason}</td></tr>
            <tr><th>Reward</th><td class="{reward_class}">{reward}</td></tr>
        </table>
    </div>
    """

    # Reward details section
    reward_details_html = ""
    if simulation.reward_info:
        ri = simulation.reward_info

        # Action checks
        action_checks_html = ""
        if hasattr(ri, "action_checks") and ri.action_checks:
            action_checks_html = (
                "<div class='reward-subsection'><strong>Action Checks:</strong><ul>"
            )
            for ac in ri.action_checks:
                action = ac.action if hasattr(ac, "action") else ac.get("action", {})
                action_name = (
                    action.name
                    if hasattr(action, "name")
                    else action.get("name", "unknown")
                )
                action_args = (
                    action.arguments
                    if hasattr(action, "arguments")
                    else action.get("arguments", {})
                )
                match = (
                    ac.action_match
                    if hasattr(ac, "action_match")
                    else ac.get("action_match", False)
                )
                match_icon = "✓" if match else "✗"
                match_class = "success" if match else "failure"

                # Format action as functional call
                tc = ToolCall(name=action_name, arguments=action_args)
                func_str = to_functional_format(tc)
                action_checks_html += f'<li><span class="{match_class}">{match_icon}</span> <code>{escape_html(func_str)}</code></li>'
            action_checks_html += "</ul></div>"

        # DB check
        db_check_html = ""
        if hasattr(ri, "db_check") and ri.db_check:
            db = ri.db_check
            db_match = (
                db.db_match if hasattr(db, "db_match") else db.get("db_match", False)
            )
            db_icon = "✓" if db_match else "✗"
            db_class = "success" if db_match else "failure"
            db_check_html = f"<div class='reward-subsection'><strong>DB Check:</strong> <span class='{db_class}'>{db_icon} {'Passed' if db_match else 'Failed'}</span></div>"

        reward_details_html = f"""
        <div class="section reward-section">
            <details>
                <summary><h2 style="display: inline; cursor: pointer;">Reward Details (Reward: <span class="{reward_class}">{reward}</span>) ▶</h2></summary>
                <div class="reward-content">
                    {db_check_html}
                    {action_checks_html}
                </div>
            </details>
        </div>
        """

    # LLM Judge Review section
    review_html = ""
    errors_json = "[]"

    if hasattr(simulation, "review") and simulation.review:
        review = simulation.review
        summary = (
            review.summary if hasattr(review, "summary") else review.get("summary", "")
        )
        agent_error = (
            review.agent_error
            if hasattr(review, "agent_error")
            else review.get("agent_error", False)
        )
        user_error = (
            review.user_error
            if hasattr(review, "user_error")
            else review.get("user_error", False)
        )
        errors = (
            review.errors if hasattr(review, "errors") else review.get("errors", [])
        )

        # Error summary badges
        badges = []
        if agent_error:
            badges.append('<span class="badge badge-agent">Agent Error</span>')
        if user_error:
            badges.append('<span class="badge badge-user">User Error</span>')
        if not agent_error and not user_error:
            badges.append('<span class="badge badge-success">No Errors</span>')
        badges_html = " ".join(badges)

        errors_data = []

        # Detailed errors
        errors_html = ""
        if errors:
            errors_html = "<div class='errors-list'>"
            for i, err in enumerate(errors):
                source = (
                    err.source
                    if hasattr(err, "source")
                    else err.get("source", "unknown")
                )
                error_tags = (
                    err.error_tags
                    if hasattr(err, "error_tags")
                    else err.get("error_tags", [])
                )
                severity = (
                    err.severity
                    if hasattr(err, "severity")
                    else err.get("severity", "")
                )
                tick_start = (
                    err.tick_start
                    if hasattr(err, "tick_start")
                    else err.get("tick_start")
                )
                tick_end = (
                    err.tick_end if hasattr(err, "tick_end") else err.get("tick_end")
                )
                reasoning = (
                    err.reasoning
                    if hasattr(err, "reasoning")
                    else err.get("reasoning", "")
                )
                correct_behavior = (
                    err.correct_behavior
                    if hasattr(err, "correct_behavior")
                    else err.get("correct_behavior", "")
                )

                # Store for JavaScript (minimal data for row highlighting)
                if tick_start is not None and tick_end is not None:
                    errors_data.append(
                        {
                            "id": i,
                            "source": source,
                            "tags": error_tags,
                            "severity": severity,
                            "tick_start": tick_start,
                            "tick_end": tick_end,
                        }
                    )

                source_class = "agent" if source == "agent" else "user"
                severity_class = (
                    "critical" if "critical" in str(severity).lower() else "minor"
                )
                tags_html = " ".join(
                    f'<span class="error-tag">{tag}</span>' for tag in error_tags
                )

                # Make tick range clickable
                if tick_start is not None and tick_end is not None:
                    tick_range = f'<span class="error-ticks clickable-error" data-tick-start="{tick_start}" data-tick-end="{tick_end}" data-error-id="{i}" title="Click to go to this section">T{tick_start}-{tick_end} ↗</span>'
                else:
                    tick_range = ""

                errors_html += f'''
                <details class="error-item error-{source_class} error-{severity_class}" data-error-id="{i}">
                    <summary>
                        <span class="error-source">{source.upper()}</span>
                        <span class="error-severity">{severity}</span>
                        {tags_html}
                        {tick_range}
                    </summary>
                    <div class="error-details">
                        <p><strong>Reasoning:</strong> {escape_html(reasoning)}</p>
                        <p><strong>Correct behavior:</strong> {escape_html(correct_behavior)}</p>
                    </div>
                </details>
                '''
            errors_html += "</div>"

        errors_json = json.dumps(errors_data)

        review_html = f"""
        <div class="section review-section">
            <details open>
                <summary>
                    <h2 style="display: inline; cursor: pointer;">LLM Judge Review {badges_html} ▶</h2>
                </summary>
                <div class="review-content">
                    <div class="review-summary">
                        <strong>Summary:</strong>
                        <p>{escape_html(summary)}</p>
                    </div>
                    {errors_html}
                </div>
            </details>
        </div>
        """

    # Audio player (now using sticky player at bottom)
    audio_html = ""
    sticky_player_html = ""
    if audio_path:
        # Small inline player for reference
        audio_html = f"""
        <div class="section" style="padding: 12px 20px;">
            <strong>Audio:</strong> {audio_filename} 
            <span style="color: #666; font-size: 12px;">(Use sticky player at bottom or keyboard: Space=play/pause, ←→=seek)</span>
        </div>
        """
        # Sticky player at bottom - simple with just native controls + keyboard hint
        sticky_player_html = f"""
        <div class="sticky-player">
            <audio id="mainAudio" controls>
                <source src="{audio_filename}" type="audio/wav">
            </audio>
            <div class="shortcut-hint">
                Keyboard: Space = play/pause | ← = -5s | → = +5s
            </div>
        </div>
        """

    # Conversation ticks
    ticks_html = generate_tick_rows(simulation)

    # Load templates
    css = _load_template("annotation.css")
    js = _load_template("annotation.js")
    js = (
        js.replace("__ERRORS_JSON__", errors_json)
        .replace("__SIMULATION_ID__", _escape_js_string(simulation.id))
        .replace("__TASK_ID__", _escape_js_string(str(simulation.task_id)))
        .replace(
            "__TRIAL__",
            str(simulation.trial if simulation.trial is not None else 0),
        )
        .replace("__BATCH_NAME__", _escape_js_string(batch_name))
    )

    # Full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task {simulation.task_id} - Simulation {simulation.id[:8]}</title>
    <style>{css}</style>
</head>
<body>
    <!-- Rater Name Modal -->
    <div class="modal-overlay" id="raterModal">
        <div class="rater-modal-content">
            <h2>Enter Your Name</h2>
            <p>Your annotations will be saved separately under your name.</p>
            <input type="text" id="raterNameInput" placeholder="e.g. Alice" 
                   onkeydown="if(event.key==='Enter') submitRaterName()">
            <button onclick="submitRaterName()">Start Annotating</button>
        </div>
    </div>

    <!-- Back to Index -->
    <a href="../index.html" class="back-link">← Back to Index</a>
    
    <!-- Rater display -->
    <span class="rater-badge" id="raterDisplay"></span>
    
    <!-- Help Button -->
    <button class="help-btn" id="helpBtn" title="Press G to open guidelines">
        📖 Guidelines <span class="shortcut">G</span>
    </button>
    
    <!-- Guidelines Modal -->
    <div class="modal-overlay" id="guidelinesModal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>📖 Annotation Guidelines</h2>
                <button class="modal-close" id="modalClose" title="Press Escape to close">&times;</button>
            </div>
            <div class="modal-body" id="guidelinesContent">
                {guidelines if guidelines else "Guidelines not available."}
            </div>
        </div>
    </div>

    <div class="container">
        <h1>Task {simulation.task_id} <span style="font-size: 14px; color: #666; font-weight: normal;">{escape_html(experiment_label)}</span></h1>
        
        {audio_html}
        {task_html}
        {policy_html}
        {eval_html}
        {meta_html}
        {reward_details_html}
        {review_html}
        
        <div class="section">
            <h2>Conversation</h2>
            
            <div class="column-toggles">
                <button class="column-toggle" data-col="tick">
                    <span class="indicator"></span> Tick
                </button>
                <button class="column-toggle" data-col="time">
                    <span class="indicator"></span> Time
                </button>
                <button class="column-toggle" data-col="agent-speech">
                    <span class="indicator"></span> Agent Speech
                </button>
                <button class="column-toggle" data-col="agent-tools">
                    <span class="indicator"></span> Agent Tools
                </button>
                <button class="column-toggle" data-col="user-speech">
                    <span class="indicator"></span> User Speech
                </button>
                <button class="column-toggle" data-col="user-tools">
                    <span class="indicator"></span> User Tools
                </button>
            </div>
            
            <table class="conversation-table">
                <thead>
                    <tr>
                        <th class="tick-col" data-col="tick">Tick</th>
                        <th class="time-col" data-col="time">Time</th>
                        <th data-col="agent-speech">Agent Speech</th>
                        <th data-col="agent-tools">Agent Tools</th>
                        <th data-col="user-speech">User Speech</th>
                        <th data-col="user-tools">User Tools</th>
                    </tr>
                </thead>
                <tbody>
                    {ticks_html}
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Annotation Form - Error Editor -->
    <div class="annotation-form" id="annotationForm">
        <h2>📝 Your Annotation</h2>
        
        <div class="readonly-info">
            <strong>Simulation:</strong> <code id="formSimulationId">{simulation.id}</code> | 
            <strong>Task:</strong> <code id="formTaskId">{simulation.task_id}</code> | 
            <strong>Trial:</strong> <code id="formTrial">{simulation.trial if simulation.trial is not None else 0}</code>
        </div>
        
        <!-- Quick Summary Section -->
        <div class="summary-section">
            <h3>📋 Quick Summary</h3>
            <p class="section-hint">High-level classification of the first critical error</p>
            
            <div class="form-row">
                <div class="form-group">
                    <label for="summaryErrorSource">Error Source</label>
                    <select id="summaryErrorSource">
                        <option value="">-- No error / Not applicable --</option>
                        <option value="agent">Agent Error</option>
                        <option value="user">User Simulator Error</option>
                        <option value="system">System Error (framework/infrastructure)</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="summaryErrorType">Error Type</label>
                    <select id="summaryErrorType">
                        <option value="">-- Select type --</option>
                        <option value="transcription">Transcription (ASR/speech-to-text)</option>
                        <option value="vad">VAD (turn-taking/interruption)</option>
                        <option value="logical">Logical (reasoning/tool call/instruction)</option>
                        <option value="hallucination">Hallucination (made up info)</option>
                        <option value="unresponsive">Unresponsive (no response/latency)</option>
                        <option value="early_termination">Early Termination (ended prematurely)</option>
                    </select>
                </div>
            </div>
            
            <div class="form-row">
                <div class="form-group wide">
                    <label for="summaryNotes">Summary Notes</label>
                    <textarea id="summaryNotes" placeholder="Brief description of what happened..."></textarea>
                </div>
            </div>
        </div>
        
        <div class="form-row complete-row">
            <label class="complete-checkbox">
                <input type="checkbox" id="markComplete">
                <span class="checkmark"></span>
                <strong>Mark as Complete</strong> — Check this when you've finished annotating this simulation
            </label>
        </div>
        
        <div class="button-row">
            <button type="button" class="btn-primary" id="copyAnnotationBtn">📋 Copy Annotation (JSON)</button>
            <button type="button" class="btn-secondary" id="downloadAnnotationBtn">💾 Download Annotation</button>
        </div>
        
        <div class="status-message" id="statusMessage"></div>
    </div>
    
    {sticky_player_html}
    
    <script>{js}</script>
</body>
</html>
"""
    return html


def load_task(domain: str, task_id: str) -> Optional[dict]:
    """Load task definition from domain's tasks.json."""
    tasks_file = DATA_DIR / "tau2" / "domains" / domain / "tasks.json"
    if not tasks_file.exists():
        return None

    with open(tasks_file) as f:
        tasks = json.load(f)

    # Find task by ID (field is "id" not "task_id")
    for task in tasks:
        if str(task.get("id")) == str(task_id):
            return task

    return None


def load_policy(domain: str) -> Optional[str]:
    """Load policy markdown from domain."""
    policy_file = DATA_DIR / "tau2" / "domains" / domain / "policy.md"
    if not policy_file.exists():
        return None

    with open(policy_file) as f:
        return f.read()


def load_guidelines() -> Optional[str]:
    """Load annotation guidelines as HTML (body content only for embedding)."""
    import re

    html_file = Path(__file__).parent / "ANNOTATION_GUIDELINES.html"
    if html_file.exists():
        with open(html_file) as f:
            content = f.read()

        # Extract style from head
        style_match = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
        style_content = style_match.group(1) if style_match else ""

        # Extract body content
        body_match = re.search(r"<body>(.*?)</body>", content, re.DOTALL)
        body_content = body_match.group(1) if body_match else content

        # Return style + body for embedding in modal
        if style_content:
            return f"<style>{style_content}</style>\n{body_content}"
        return body_content

    # Fall back to markdown (will be displayed as preformatted text)
    md_file = Path(__file__).parent / "ANNOTATION_GUIDELINES.md"
    if md_file.exists():
        with open(md_file) as f:
            return f"<pre>{f.read()}</pre>"

    return None


# =============================================================================
# Results-based export (new mode)
# =============================================================================

REWARD_FILTER_PATTERN = re.compile(r"^\s*([<>=!]+)\s*([0-9]*\.?[0-9]+)\s*$")

REWARD_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def _parse_reward_filter(filter_str: str) -> tuple:
    """Parse a reward filter string like '< 1' into (operator_fn, threshold)."""
    match = REWARD_FILTER_PATTERN.match(filter_str)
    if not match:
        raise ValueError(
            f"Invalid reward filter: '{filter_str}'. "
            "Expected format: '<op> <value>' (e.g., '< 1', '== 0', '>= 0.5')"
        )
    op_str, value_str = match.group(1), match.group(2)
    if op_str not in REWARD_OPS:
        raise ValueError(
            f"Unknown operator '{op_str}'. Supported: {', '.join(REWARD_OPS)}"
        )
    return REWARD_OPS[op_str], float(value_str)


def load_and_filter_results(
    results_path: Path,
    domain_override: Optional[str] = None,
    filter_reward: Optional[str] = None,
    filter_tasks: Optional[list[str]] = None,
    filter_trials: Optional[list[int]] = None,
    max_items: Optional[int] = None,
) -> list[tuple[SimulationRun, str, Path, str]]:
    """
    Load simulation results and apply filters.

    Args:
        results_path: Path to a results.json file or a directory containing them.
        domain_override: Override the domain auto-detected from results.
        filter_reward: Reward filter expression (e.g., "< 1", "== 0").
        filter_tasks: Only include these task IDs.
        filter_trials: Only include these trial numbers.
        max_items: Maximum number of simulations to return.

    Returns:
        List of (SimulationRun, domain, results_dir, experiment_label) tuples.
    """
    if results_path.is_file():
        results_files = [results_path]
    elif results_path.is_dir():
        results_files = sorted(results_path.rglob("results.json"))
        if not results_files:
            raise FileNotFoundError(f"No results.json files found in {results_path}")
    else:
        raise FileNotFoundError(f"Path does not exist: {results_path}")

    reward_op = None
    reward_threshold = None
    if filter_reward:
        reward_op, reward_threshold = _parse_reward_filter(filter_reward)

    entries: list[tuple[SimulationRun, str, Path, str]] = []

    for i, rf in enumerate(results_files, 1):
        print(f"Loading results [{i}/{len(results_files)}]: {rf}")
        results = Results.load(rf)
        results_dir = rf.parent

        domain = domain_override or results.info.environment_info.domain_name
        experiment_label = results_dir.name

        for sim in results.simulations:
            if filter_tasks and str(sim.task_id) not in filter_tasks:
                continue

            if filter_trials and sim.trial not in filter_trials:
                continue

            if reward_op is not None and reward_threshold is not None:
                reward = sim.reward_info.reward if sim.reward_info else None
                if reward is None or not reward_op(reward, reward_threshold):
                    continue

            entries.append((sim, domain, results_dir, experiment_label))

    if max_items is not None:
        entries = entries[:max_items]

    return entries


def export_simulation(
    simulation: SimulationRun,
    output_dir: Path,
    domain: str,
    results_dir: Path,
    copy_audio: bool = True,
    batch_name: str = "",
    experiment_label: str = "",
) -> Optional[Path]:
    """Export a single simulation to HTML (no note file required).

    Args:
        simulation: The SimulationRun to export.
        output_dir: Root output directory.
        domain: Domain name for loading task/policy.
        results_dir: Directory containing the results.json (used to find audio).
        copy_audio: Whether to copy audio files into the output.
        batch_name: Batch identifier for localStorage namespacing.
        experiment_label: Human-readable experiment name (e.g. dir name + provider).

    Returns:
        Path to the generated HTML file, or None on failure.
    """
    task = load_task(domain, simulation.task_id)
    policy = load_policy(domain)
    guidelines = load_guidelines()

    output_subdir = output_dir / f"task_{simulation.task_id}_sim_{simulation.id}"
    output_subdir.mkdir(parents=True, exist_ok=True)

    audio_filename = None
    audio_search_paths = [
        results_dir
        / "tasks"
        / f"task_{simulation.task_id}"
        / f"sim_{simulation.id}"
        / "audio"
        / "both.wav",
        results_dir
        / "tasks"
        / f"task_{simulation.task_id}"
        / f"sim_{simulation.id}"
        / "both.wav",
    ]
    for audio_file in audio_search_paths:
        if audio_file.exists():
            if copy_audio:
                audio_filename = "audio.wav"
                shutil.copy(audio_file, output_subdir / audio_filename)
            break

    html = generate_html(
        simulation=simulation,
        task=task,
        audio_path=audio_filename,
        audio_filename=audio_filename or "",
        domain=domain,
        policy=policy,
        guidelines=guidelines,
        batch_name=batch_name,
        experiment_label=experiment_label,
    )

    html_file = output_subdir / "index.html"
    with open(html_file, "w") as f:
        f.write(html)

    return html_file


def generate_index_page(
    exported_files: list[Path],
    output_dir: Path,
    entry_metadata: list[dict],
    batch_name: str = "",
):
    """Generate the index HTML page listing all exported annotations.

    Args:
        exported_files: List of HTML file paths that were exported.
        output_dir: Root output directory (for computing relative paths).
        entry_metadata: List of dicts with "task_id" and "simulation_id" per entry,
            in the same order as exported_files.
        batch_name: Batch identifier for localStorage namespacing.
    """
    index_css = _load_template("index.css")
    index_js = _load_template("index.js").replace("__BATCH_NAME__", _escape_js_string(batch_name))

    index_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{batch_name} - Annotation Index</title>
    <style>{index_css}</style>
</head>
<body>
    <!-- Rater Name Modal -->
    <div class="modal-overlay" id="raterModal">
        <div class="rater-modal-content">
            <h2>Enter Your Name</h2>
            <p>Your annotations will be saved separately under your name.</p>
            <input type="text" id="raterNameInput" placeholder="e.g. Alice"
                   onkeydown="if(event.key==='Enter') submitRaterName()">
            <button onclick="submitRaterName()">Start Annotating</button>
        </div>
    </div>

    <div class="header">
        <h1>{batch_name} <span class="rater-badge" id="raterDisplay"></span></h1>
    </div>
    
    <div class="export-section">
        <div class="stats">
            <span id="completedCount">0</span> completed · 
            <span id="inProgressCount">0</span> in progress · 
            <span id="pendingCount">0</span> pending
        </div>
        <div>
            <input type="file" id="csvFileInput" accept=".csv" style="display: none;" onchange="importFromCSV(event)">
            <button class="btn btn-tertiary" onclick="document.getElementById('csvFileInput').click()">📤 Import CSV</button>
            <button class="btn btn-secondary" onclick="clearAnnotations()">Clear All</button>
            <button class="btn" onclick="exportToCSV()">📥 Export All to CSV</button>
        </div>
    </div>
    
    <div id="importStatus" class="import-status"></div>
    
    <table id="taskTable">
        <thead>
            <tr>
                <th class="sortable" data-sort="task" data-type="number">Task <span class="sort-arrow"></span></th>
                <th class="sortable" data-sort="experiment">Experiment <span class="sort-arrow"></span></th>
                <th class="sortable" data-sort="status">Status <span class="sort-arrow"></span></th>
            </tr>
        </thead>
        <tbody id="taskList">
"""

    sorted_pairs = sorted(zip(exported_files, entry_metadata), key=lambda p: p[0])
    for html_file, meta in sorted_pairs:
        rel_path = html_file.relative_to(output_dir)
        task_id = meta.get("task_id", "")
        sim_id = meta.get("simulation_id", "")
        experiment = escape_html(meta.get("experiment", ""))
        index_html += f'        <tr data-task="{task_id}" data-sim="{sim_id}"><td><a href="{rel_path}">Task {task_id}</a></td><td class="experiment-col">{experiment}</td><td><span class="status pending">pending</span></td></tr>\n'

    index_html += f"""        </tbody>
    </table>
    
    <script>{index_js}</script>
</body>
</html>
"""

    index_path = output_dir / "index.html"
    with open(index_path, "w") as f:
        f.write(index_html)
    return index_path


def _run_results_mode(args) -> None:
    """Export simulations from results.json files (new mode)."""
    filter_tasks = None
    if args.filter_tasks:
        filter_tasks = [t.strip() for t in args.filter_tasks.split(",")]

    filter_trials = None
    if args.filter_trials:
        filter_trials = [int(t.strip()) for t in args.filter_trials.split(",")]

    entries = load_and_filter_results(
        results_path=args.results,
        domain_override=args.domain,
        filter_reward=args.filter_reward,
        filter_tasks=filter_tasks,
        filter_trials=filter_trials,
        max_items=args.max_items,
    )

    print(f"Found {len(entries)} simulations to export")
    if not entries:
        print("Nothing to export.")
        return

    if args.output_dir.exists():
        print(f"Error: Output directory already exists: {args.output_dir}")
        print("Remove it first or choose a different path.")
        raise SystemExit(1)

    args.output_dir.mkdir(parents=True)

    exported = []
    metadata = []
    for sim, domain, results_dir, experiment_label in entries:
        reward = sim.reward_info.reward if sim.reward_info else None
        reward_str = f" (reward={reward:.2f})" if reward is not None else ""
        print(f"Exporting: task {sim.task_id} / sim {sim.id}{reward_str} [{experiment_label}]")

        html_file = export_simulation(
            simulation=sim,
            output_dir=args.output_dir,
            domain=domain,
            results_dir=results_dir,
            copy_audio=not args.no_copy_audio,
            batch_name=args.batch_name,
            experiment_label=experiment_label,
        )
        if html_file:
            exported.append(html_file)
            metadata.append({
                "task_id": str(sim.task_id),
                "simulation_id": sim.id,
                "experiment": experiment_label,
            })
            print(f"  -> {html_file}")

    print(f"\nExported {len(exported)} simulations to {args.output_dir}")

    if exported:
        index_path = generate_index_page(exported, args.output_dir, metadata, args.batch_name)
        print(f"Index page: {index_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export simulation data to HTML for annotation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Export failed simulations
  %(prog)s --batch-name round1_retail --results path/to/results.json --filter-reward "< 1"

  # Export from a directory of experiments
  %(prog)s --batch-name round1_all --results path/to/experiment_dir/ --filter-reward "< 1"

  # Export with a cap
  %(prog)s --batch-name quick_test --results path/to/results/ --max-items 5
""",
    )

    parser.add_argument(
        "--batch-name",
        type=str,
        required=True,
        help="Name for this annotation batch (used as output directory and localStorage namespace)",
    )
    parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="Path to results.json file or directory containing results",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/annotations"),
        help="Parent directory for batch output (default: data/annotations/)",
    )
    parser.add_argument(
        "--no-copy-audio",
        action="store_true",
        default=False,
        help="Skip copying audio files to output directory",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Override domain (auto-detected from results if omitted)",
    )
    parser.add_argument(
        "--filter-reward",
        type=str,
        default=None,
        help='Filter by reward (e.g., "< 1", "== 0", ">= 0.5")',
    )
    parser.add_argument(
        "--filter-tasks",
        type=str,
        default=None,
        help="Comma-separated task IDs to include",
    )
    parser.add_argument(
        "--filter-trials",
        type=str,
        default=None,
        help="Comma-separated trial numbers to include",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Maximum number of simulations to export",
    )

    args = parser.parse_args()
    args.output_dir = args.output_root / args.batch_name
    _run_results_mode(args)


if __name__ == "__main__":
    main()
