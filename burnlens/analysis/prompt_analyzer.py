"""Local tokenization, payload parsing, and prompt section classification for BurnLens."""
from __future__ import annotations

import json
import re
from typing import Any, Tuple

try:
    import tiktoken
    _encoding = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _encoding = None

# Delimiters indicating RAG/Context blocks
_RAG_XML_PATTERNS = [
    re.compile(r"<(doc|document|context|source|wikipedia|retrieved|docs)[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE),
]

_RAG_HEADER_PATTERNS = [
    re.compile(r"(?:^|\n)(?:Context|Source|Reference|Search\s+results|Retrieved\s+documents|Background\s+info|Context\s+documents):\s*\n*(.*?)(?=\n\n|\n[A-Z][a-zA-Z\s]+:|$)", re.DOTALL | re.IGNORECASE),
]

_RAG_DIVIDER_PATTERN = re.compile(r"(?:^|\n)(?:---|===)\s*\n*(.*?)\n*(?:---|===|$)", re.DOTALL)


def count_tokens(text: str) -> int:
    """Return the number of tokens in text using cl100k_base, falling back to char approximation."""
    if not text:
        return 0
    if _encoding is not None:
        try:
            return len(_encoding.encode(text))
        except Exception:
            pass
    # Fallback to ~4 characters per token
    return max(1, len(text) // 4)


def extract_rag_content(text: str) -> Tuple[str, str]:
    """Extract RAG/Context blocks from text.

    Returns:
        (remaining_text, extracted_rag_text)
    """
    if not text:
        return "", ""

    rag_blocks = []
    remaining_text = text

    # 1. XML tags
    for pattern in _RAG_XML_PATTERNS:
        matches = list(pattern.finditer(remaining_text))
        # Process from back to front to preserve offsets during replacement
        for m in reversed(matches):
            rag_blocks.append(m.group(2).strip())
            remaining_text = remaining_text[:m.start()] + remaining_text[m.end():]

    # 2. RAG Headers
    for pattern in _RAG_HEADER_PATTERNS:
        matches = list(pattern.finditer(remaining_text))
        for m in reversed(matches):
            rag_blocks.append(m.group(1).strip())
            remaining_text = remaining_text[:m.start()] + remaining_text[m.end():]

    # 3. Markdown Dividers (only if the divided block is sufficiently large, e.g. > 150 chars)
    matches = list(_RAG_DIVIDER_PATTERN.finditer(remaining_text))
    for m in reversed(matches):
        block = m.group(1).strip()
        if len(block) > 150:
            rag_blocks.append(block)
            remaining_text = remaining_text[:m.start()] + remaining_text[m.end():]

    rag_text = "\n\n".join(rag_blocks)
    return remaining_text.strip(), rag_text.strip()


def parse_messages(messages: list[dict[str, Any]]) -> Tuple[str, str]:
    """Parse messages list into history and final user query text.

    Returns:
        (history_text, query_text)
    """
    if not messages:
        return "", ""

    # Filter out system messages (usually OpenAI maps them here)
    chat_turns = [m for m in messages if m.get("role") != "system"]
    if not chat_turns:
        return "", ""

    # The last message is the query
    query_turn = chat_turns[-1]
    query_content = query_turn.get("content", "")
    
    # Handle list-based contents (multi-modal or structured text)
    query_text = ""
    if isinstance(query_content, str):
        query_text = query_content
    elif isinstance(query_content, list):
        query_text = "".join(
            part.get("text", "") for part in query_content if isinstance(part, dict)
        )

    # All prior turns are history
    history_blocks = []
    for turn in chat_turns[:-1]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if isinstance(content, str):
            history_blocks.append(f"{role}: {content}")
        elif isinstance(content, list):
            text = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
            history_blocks.append(f"{role}: {text}")

    history_text = "\n\n".join(history_blocks)
    return history_text, query_text


def parse_system_instruction(system_instruction: Any) -> str:
    """Parse system instruction object (usually Google format) into text."""
    if not system_instruction:
        return ""
    if isinstance(system_instruction, str):
        return system_instruction
    if isinstance(system_instruction, dict):
        parts = system_instruction.get("parts") or []
        if isinstance(parts, list):
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return ""


def analyze_request_prompt(
    provider: str,
    model: str,
    body_bytes: bytes,
    input_tokens: int,
) -> dict[str, int]:
    """Parse request payload, tokenize sections, scale to billed input_tokens.

    Returns:
        dict with:
        - prompt_system_tokens
        - prompt_user_tokens
        - prompt_tools_tokens
        - prompt_rag_tokens
        - prompt_history_tokens
    """
    if not body_bytes:
        return {
            "prompt_system_tokens": 0,
            "prompt_user_tokens": input_tokens,
            "prompt_tools_tokens": 0,
            "prompt_rag_tokens": 0,
            "prompt_history_tokens": 0,
        }

    try:
        body = json.loads(body_bytes)
    except Exception:
        # If parsing fails, fall back to allocating everything to user
        return {
            "prompt_system_tokens": 0,
            "prompt_user_tokens": input_tokens,
            "prompt_tools_tokens": 0,
            "prompt_rag_tokens": 0,
            "prompt_history_tokens": 0,
        }

    # Extract raw sections
    system_text = ""
    tools_text = ""
    history_text = ""
    query_text = ""
    rag_text = ""

    # 1. System Prompt
    # OpenAI/Google system messages
    messages = body.get("messages") or []
    system_msgs = [m for m in messages if m.get("role") == "system"]
    for m in system_msgs:
        content = m.get("content", "")
        if isinstance(content, str):
            system_text += "\n" + content
        elif isinstance(content, list):
            system_text += "\n" + "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

    # Anthropic top-level system parameter
    anthropic_system = body.get("system")
    if anthropic_system:
        if isinstance(anthropic_system, str):
            system_text += "\n" + anthropic_system
        elif isinstance(anthropic_system, list):
            for block in anthropic_system:
                if isinstance(block, dict) and block.get("type") == "text":
                    system_text += "\n" + block.get("text", "")

    # Google systemInstruction
    google_system = body.get("systemInstruction")
    if google_system:
        system_text += "\n" + parse_system_instruction(google_system)

    system_text = system_text.strip()

    # 2. Tools
    # OpenAI & Anthropic have "tools", Google has "tools" as list of functionDeclarations
    tools = body.get("tools") or body.get("functions")
    if tools:
        try:
            tools_text = json.dumps(tools)
        except Exception:
            pass

    # 3. Messages / History / Query
    # Google uses "contents" instead of "messages"
    google_contents = body.get("contents")
    if google_contents:
        # Standardize Google contents as messages for parsing
        standardized_msgs = []
        for turn in google_contents:
            role = turn.get("role", "user")
            parts = turn.get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            standardized_msgs.append({"role": role, "content": text})
        history_text, query_text = parse_messages(standardized_msgs)
    elif messages:
        history_text, query_text = parse_messages(messages)

    # 4. RAG Extraction
    # Scan both system_text and query_text for RAG content
    clean_system, system_rag = extract_rag_content(system_text)
    clean_query, query_rag = extract_rag_content(query_text)

    system_text = clean_system
    query_text = clean_query
    rag_text = "\n\n".join(filter(None, [system_rag, query_rag]))

    # Compute raw token counts
    raw_system = count_tokens(system_text)
    raw_tools = count_tokens(tools_text)
    raw_history = count_tokens(history_text)
    raw_query = count_tokens(query_text)
    raw_rag = count_tokens(rag_text)

    total_raw = raw_system + raw_tools + raw_history + raw_query + raw_rag

    if total_raw == 0:
        return {
            "prompt_system_tokens": 0,
            "prompt_user_tokens": input_tokens,
            "prompt_tools_tokens": 0,
            "prompt_rag_tokens": 0,
            "prompt_history_tokens": 0,
        }

    # Proportional Scaling to align exactly with billed input_tokens
    # prompt_system_tokens + prompt_user_tokens + prompt_tools_tokens + prompt_rag_tokens + prompt_history_tokens == input_tokens
    scale = input_tokens / total_raw
    scaled = {
        "prompt_system_tokens": round(raw_system * scale),
        "prompt_tools_tokens": round(raw_tools * scale),
        "prompt_history_tokens": round(raw_history * scale),
        "prompt_rag_tokens": round(raw_rag * scale),
        "prompt_user_tokens": round(raw_query * scale),
    }

    # Ensure no negative values
    for k in scaled:
        scaled[k] = max(0, scaled[k])

    # Adjust discrepancy to match input_tokens exactly
    current_sum = sum(scaled.values())
    diff = input_tokens - current_sum
    if diff != 0:
        # Apply the discrepancy adjustment to the largest field.
        # Since the rounding discrepancy is at most 2-3 tokens, the largest field
        # will always have enough tokens to absorb it without going negative.
        largest_key = max(scaled, key=lambda k: scaled[k])
        scaled[largest_key] = max(0, scaled[largest_key] + diff)

        # safety pass: force sum equality
        current_sum = sum(scaled.values())
        diff = input_tokens - current_sum
        if diff != 0:
            scaled["prompt_user_tokens"] = max(0, scaled["prompt_user_tokens"] + diff)

    return scaled

