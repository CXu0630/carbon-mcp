"""Chat with the carbon MCP server through a local Ollama model.

    ollama pull qwen3:4b-instruct-2507-q4_K_M
    uv run python scripts/local_agent.py                       # interactive
    uv run python scripts/local_agent.py "200 mm RC slab vs 200 mm CLT + 50 mm topping, A1-A3 per m2?"
    uv run python scripts/local_agent.py --log demo/agent.md "..."   # also save a transcript

Env: OLLAMA_HOST (default http://localhost:11434), OLLAMA_MODEL.
The script is the MCP client: it lists the server's tools, hands their schemas to the
model, executes the model's tool calls over MCP, and feeds results back.
"""
import argparse
import asyncio
import copy
import json
import os
import sys
import urllib.request
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
MAX_STEPS = 8

SYSTEM = (
    "You estimate embodied carbon of building assemblies using tools. Never compute numbers "
    "yourself; call a tool. If the user names a material without a factor or density, call "
    "lookup_material_factor (factor) or lookup_density (density). If a factor is per m3 or m2, "
    "call convert_units to get kgCO2e/kg. One layer -> compute_layer_carbon; several layers -> "
    "compute_assembly_carbon, one call per assembly; shipping -> compute_transport_carbon; "
    "carbon stored in wood -> compute_biogenic_carbon. Do not repeat an identical call. If a "
    "tool returns an error, fix the arguments or ask the user. Answer with units and life-cycle "
    "module (A1-A3, A4); report biogenic storage separately, never subtracted from A1-A3; name "
    "the dataset or assumption each number depends on."
)


def _inline_refs(schema):
    """Small models handle flat schemas better than $ref/$defs."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/$defs/"):
                return walk(copy.deepcopy(defs[ref.split("/")[-1]]))
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(schema)


def ollama_chat(messages, tools):
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tools, "stream": False,
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(f"{HOST}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)["message"]
    except OSError as exc:
        sys.exit(f"Cannot reach Ollama at {HOST} ({exc}). Is `ollama serve` running and "
                 f"`ollama pull {MODEL}` done?")


async def ask(client, tools, question):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    trace, seen = [], set()
    for _ in range(MAX_STEPS):
        msg = ollama_chat(messages, tools)
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content", ""), trace
        for call in calls:
            name = call["function"]["name"]
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):  # some models send a JSON string
                args = json.loads(args or "{}")
            key = (name, json.dumps(args, sort_keys=True))
            if key in seen:
                content = "ERROR: identical call already made; use its result."
                is_error, data = True, None
            else:
                seen.add(key)
                res = await client.call_tool(name, args)
                is_error = res.is_error
                data = res.structured_content
                text = " ".join(c.text for c in res.content if getattr(c, "type", "") == "text")
                content = ("ERROR: " + text) if is_error else json.dumps(data if data is not None
                                                                         else text)
            trace.append({"tool": name, "arguments": args, "is_error": is_error,
                          "result": data if not is_error else content})
            print(f"  → {name}({json.dumps(args)[:160]}) {'ERROR' if is_error else 'ok'}",
                  file=sys.stderr)
            messages.append({"role": "tool", "tool_name": name, "content": content})
    return "Stopped: step limit reached without a final answer.", trace


def write_log(path, question, answer, trace):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"## Q: {question}\n\nModel: `{MODEL}`\n"]
    for t in trace:
        parts.append(f"**`{t['tool']}`** — isError: {str(t['is_error']).lower()}\n\n"
                     f"```json\n{json.dumps(t['arguments'], indent=2, ensure_ascii=False)}\n```\n"
                     f"```json\n{json.dumps(t['result'], indent=2, ensure_ascii=False)[:4000]}\n```\n")
    parts.append(f"**Answer**\n\n{answer}\n\n---\n")
    with path.open("a") as f:
        f.write("\n".join(parts))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--log", help="append a markdown transcript, e.g. demo/agent.md")
    a = ap.parse_args()

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        p for p in (str(ROOT / "src"), os.environ.get("PYTHONPATH")) if p)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "carbon_mcp.server"],
                                   cwd=str(ROOT), env=env)
    async with Client(params) as client:
        tools = [{"type": "function", "function": {
            "name": t.name, "description": t.description or "",
            "parameters": _inline_refs(t.input_schema)}}
            for t in (await client.list_tools()).tools]
        print(f"{MODEL} with {len(tools)} MCP tools. Ctrl-D to quit.", file=sys.stderr)

        questions = [a.question] if a.question else None
        while True:
            if questions is not None:
                if not questions:
                    break
                q = questions.pop()
            else:
                try:
                    q = input("\nyou> ").strip()
                except EOFError:
                    break
                if not q:
                    continue
            answer, trace = await ask(client, tools, q)
            print(f"\n{answer}\n")
            if a.log:
                write_log(a.log, q, answer, trace)


if __name__ == "__main__":
    asyncio.run(main())
