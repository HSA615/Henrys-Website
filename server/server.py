#!/usr/bin/env python3
"""
Remote Claude Code Server (Groq edition)
Lets you control your PC with an AI from any browser (e.g. your phone).

Setup:
  pip install websockets groq

Run:
  python server.py --token AlbertsHenry123 --cwd C:/Users/scalb

Expose to internet:
  cloudflared tunnel --url http://localhost:7823
"""
import asyncio
import json
import subprocess
import os
import sys
import argparse
from pathlib import Path

try:
    import websockets
    import groq as groq_lib
except ImportError:
    print("Missing packages. Run:  pip install websockets groq")
    sys.exit(1)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command on the user's PC. Use for running scripts, "
                "installing packages, git commands, compiling code, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 60)"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's contents",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and folders at a path",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path (default: cwd)"}},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "change_directory",
            "description": "Change the current working directory",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        }
    }
]


def resolve_path(p: str, cwd: str) -> Path:
    path = Path(p)
    return (Path(cwd) / path).resolve() if not path.is_absolute() else path.resolve()


def run_tool(name: str, args: dict, cwd: str) -> tuple[str, str | None]:
    """Returns (result_text, new_cwd_or_None)"""
    try:
        if name == "bash":
            cmd = args.get("command", "")
            timeout = int(args.get("timeout", 60))
            r = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=timeout, cwd=cwd,
                encoding="utf-8", errors="replace"
            )
            out = (r.stdout or "").rstrip()
            err = (r.stderr or "").rstrip()
            parts = []
            if out:
                parts.append(out)
            if err:
                parts.append(("STDERR:\n" if out else "") + err)
            if not parts and r.returncode != 0:
                parts.append(f"Exit code: {r.returncode}")
            return ("\n".join(parts) or "(no output)"), None

        elif name == "read_file":
            p = resolve_path(args.get("path", ""), cwd)
            text = p.read_text(encoding="utf-8", errors="replace")
            if len(text) > 30000:
                text = text[:30000] + f"\n...(truncated — {len(text)} chars total)"
            return text, None

        elif name == "write_file":
            p = resolve_path(args.get("path", ""), cwd)
            p.parent.mkdir(parents=True, exist_ok=True)
            content = args.get("content", "")
            p.write_text(content, encoding="utf-8")
            return f"Written {len(content)} chars to {p}", None

        elif name == "list_directory":
            raw = args.get("path", "") or cwd
            p = resolve_path(raw, cwd)
            items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            lines = []
            for item in items:
                if item.is_dir():
                    lines.append(f"📁 {item.name}/")
                else:
                    size = item.stat().st_size
                    size_str = f"{size:,}B" if size < 1024 else f"{size//1024}KB"
                    lines.append(f"📄 {item.name}  ({size_str})")
            return "\n".join(lines) if lines else "(empty)", None

        elif name == "change_directory":
            p = resolve_path(args.get("path", ""), cwd)
            if p.is_dir():
                return f"Changed to {p}", str(p)
            else:
                return f"Not a directory: {p}", None

    except subprocess.TimeoutExpired:
        return f"Timed out after {args.get('timeout', 60)}s", None
    except FileNotFoundError as e:
        return f"File not found: {e}", None
    except PermissionError as e:
        return f"Permission denied: {e}", None
    except Exception as e:
        return f"Error ({type(e).__name__}): {e}", None

    return f"Unknown tool: {name}", None


async def agent_loop(ws, client, model: str, messages: list, cwd: str, system: str) -> str:
    """Run the agentic loop, streaming text to the websocket. Returns final cwd."""

    while True:
        # Stream the response
        text_so_far = ""
        tool_calls_buf: dict[int, dict] = {}  # index → {id, name, args}
        finish_reason = None

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}] + messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=8192,
                stream=True
            )

            async for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                # Stream text
                if delta.content:
                    text_so_far += delta.content
                    await ws.send(json.dumps({"type": "text", "content": delta.content}))

                # Accumulate tool call chunks
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {"id": "", "name": "", "args": ""}
                        if tc.id:
                            tool_calls_buf[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls_buf[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_calls_buf[idx]["args"] += tc.function.arguments

        except groq_lib.APIStatusError as e:
            await ws.send(json.dumps({
                "type": "error",
                "message": f"Groq API error {e.status_code}: {e.message}"
            }))
            return cwd
        except groq_lib.APIConnectionError:
            await ws.send(json.dumps({
                "type": "error",
                "message": "Could not connect to Groq API. Check your API key and internet."
            }))
            return cwd
        except Exception as e:
            await ws.send(json.dumps({"type": "error", "message": str(e)}))
            return cwd

        # No tool calls — we're done with this turn
        if finish_reason != "tool_calls" or not tool_calls_buf:
            if text_so_far:
                messages.append({"role": "assistant", "content": text_so_far})
            break

        # Build the assistant message with tool_calls for history
        tool_call_list = []
        for idx in sorted(tool_calls_buf.keys()):
            tc = tool_calls_buf[idx]
            tool_call_list.append({
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["args"]}
            })

        messages.append({
            "role": "assistant",
            "content": text_so_far or None,
            "tool_calls": tool_call_list
        })

        # Execute each tool and collect results
        tool_result_msgs = []
        for tc in tool_call_list:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}

            await ws.send(json.dumps({
                "type": "tool_call",
                "id": tc["id"],
                "name": name,
                "input": args
            }))

            result_text, new_cwd = run_tool(name, args, cwd)
            if new_cwd:
                cwd = new_cwd
                await ws.send(json.dumps({"type": "cwd_changed", "path": cwd}))

            display = result_text[:6000] + ("..." if len(result_text) > 6000 else "")
            await ws.send(json.dumps({
                "type": "tool_result",
                "id": tc["id"],
                "name": name,
                "result": display
            }))

            tool_result_msgs.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text[:80000]
            })

        messages.extend(tool_result_msgs)

    return cwd


async def handle_ws(ws, auth_token: str, default_cwd: str):
    addr = ws.remote_address
    print(f"[+] {addr[0]}:{addr[1]} connected")

    messages: list = []
    cwd = default_cwd
    api_key: str = ""
    model: str = "llama-3.3-70b-versatile"
    authed = not auth_token

    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = data.get("type")

            if t == "auth":
                if auth_token and data.get("token") != auth_token:
                    await ws.send(json.dumps({"type": "error", "message": "Invalid token"}))
                    await ws.close()
                    return
                api_key = data.get("api_key", "")
                model = data.get("model", "llama-3.3-70b-versatile")
                authed = True
                await ws.send(json.dumps({"type": "auth_ok", "cwd": cwd}))
                print(f"    Authenticated  model={model}  cwd={cwd}")

            elif not authed:
                await ws.send(json.dumps({"type": "error", "message": "Not authenticated."}))

            elif t == "message":
                content = data.get("content", "").strip()
                if not content or not api_key:
                    if not api_key:
                        await ws.send(json.dumps({"type": "error", "message": "No API key set."}))
                    continue

                messages.append({"role": "user", "content": content})
                client = groq_lib.AsyncGroq(api_key=api_key)
                os_name = "Windows" if os.name == "nt" else "Unix/Linux/Mac"
                system = (
                    f"You are an AI coding assistant with full access to the user's computer.\n"
                    f"Working directory: {cwd}\n"
                    f"OS: {os_name}\n\n"
                    f"You can run shell commands, read and write files, and help with any coding "
                    f"or computer task. Always explain what you're doing before using tools."
                )
                cwd = await agent_loop(ws, client, model, messages, cwd, system)
                await ws.send(json.dumps({"type": "done"}))

            elif t == "clear":
                messages = []
                await ws.send(json.dumps({"type": "cleared"}))

            elif t == "set_cwd":
                p = Path(data.get("path", ""))
                if p.is_dir():
                    cwd = str(p.resolve())
                    await ws.send(json.dumps({"type": "cwd_changed", "path": cwd}))
                else:
                    await ws.send(json.dumps({"type": "error", "message": f"Not a directory: {p}"}))

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        print(f"[-] {addr[0]}:{addr[1]} disconnected")


async def main():
    ap = argparse.ArgumentParser(description="Remote AI Code Server (Groq)")
    ap.add_argument("--port", type=int, default=7823)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default="", help="Auth token clients must send")
    ap.add_argument("--cwd", default=str(Path.home()), help="Default working directory")
    args = ap.parse_args()

    cwd = str(Path(args.cwd).resolve())

    print(f"\n{'='*52}")
    print(f"  AI Code Server (Groq)")
    print(f"{'='*52}")
    print(f"  Listening:   ws://localhost:{args.port}")
    print(f"  Working dir: {cwd}")
    print(f"  Auth token:  {args.token or '(none)'}")
    print(f"{'='*52}")
    print(f"\n  Tunnel:  cloudflared tunnel --url http://localhost:{args.port}")
    print(f"\n  Ctrl+C to stop\n")

    handler = lambda ws: handle_ws(ws, args.token, cwd)
    async with websockets.serve(handler, args.host, args.port):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
