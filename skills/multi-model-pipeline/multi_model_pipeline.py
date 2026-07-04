"""
3-Stage Multi-Model Pipeline
----------------------------
Stage 1 — Reader  : claude-haiku-4-5   → parse & compress input (minimal tokens)
Stage 2 — Reasoner: claude-opus-4-7    → deep reasoning with adaptive thinking
Stage 3 — Writer  : claude-sonnet-4-6  → clean final response

Usage:
    python multi_model_pipeline.py "your question here"
    python multi_model_pipeline.py  # reads from stdin
"""

import sys
import anthropic

client = anthropic.Anthropic()

# ── System prompts (stable → prompt-cacheable) ──────────────────────────────

READER_SYSTEM = """\
You are an input parser. Your only job is to extract and compress the user's request.
Output a structured JSON with these fields:
- intent: the main goal in one sentence
- key_concepts: list of important terms or entities
- constraints: any stated requirements or limitations
- context_summary: any background information, compressed to essentials

Be extremely concise. Never answer the question — only parse it."""

REASONER_SYSTEM = """\
You are an expert engineer and problem solver. You receive a structured summary of a
user request and must reason through the best solution. Think step-by-step.
Output a detailed reasoning plan: what to do, why, and how. Be thorough."""

WRITER_SYSTEM = """\
You are a clear, concise technical writer. You receive a reasoning plan and must
turn it into a polished final response for the user. Write directly and helpfully.
Do not explain that you are writing based on a plan — just write the answer."""


def stage1_read(user_prompt: str) -> str:
    """Haiku: parse & compress the input."""
    print("[Stage 1] Reading input with claude-haiku-4-5 ...", file=sys.stderr)
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": READER_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )
    compressed = response.content[0].text
    print(f"[Stage 1] Done. Input tokens: {response.usage.input_tokens}, "
          f"Output tokens: {response.usage.output_tokens}", file=sys.stderr)
    return compressed


def stage2_reason(compressed_input: str) -> str:
    """Opus 4.7: deep reasoning with adaptive thinking."""
    print("[Stage 2] Reasoning with claude-opus-4-7 (adaptive thinking) ...", file=sys.stderr)
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=[
            {
                "type": "text",
                "text": REASONER_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Here is the parsed user request:\n\n{compressed_input}",
            }
        ],
    )
    # Collect all text blocks (skip thinking blocks for the writer)
    reasoning_text = "\n\n".join(
        block.text for block in response.content if block.type == "text"
    )
    print(f"[Stage 2] Done. Input tokens: {response.usage.input_tokens}, "
          f"Output tokens: {response.usage.output_tokens}", file=sys.stderr)
    return reasoning_text


def stage3_write(reasoning: str, original_prompt: str) -> str:
    """Sonnet 4.6: write the final clean response."""
    print("[Stage 3] Writing response with claude-sonnet-4-6 ...", file=sys.stderr)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": WRITER_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Original user question:\n{original_prompt}\n\n"
                    f"Reasoning plan:\n{reasoning}"
                ),
            }
        ],
    )
    final = response.content[0].text
    print(f"[Stage 3] Done. Input tokens: {response.usage.input_tokens}, "
          f"Output tokens: {response.usage.output_tokens}", file=sys.stderr)
    return final


def run_pipeline(user_prompt: str) -> str:
    compressed = stage1_read(user_prompt)
    reasoning  = stage2_reason(compressed)
    answer     = stage3_write(reasoning, user_prompt)
    return answer


if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        print("Enter your question (Ctrl+D / Ctrl+Z to submit):", file=sys.stderr)
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("Error: no input provided.", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60 + "\n", file=sys.stderr)
    result = run_pipeline(prompt)
    print(result)
