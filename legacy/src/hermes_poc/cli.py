from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from hermes_poc.config import build_config
from hermes_poc.runtime import HermesRuntime
from hermes_poc.tts import TTSClient


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = build_config(Path.cwd(), user_id=args.user_id, session_id=args.session_id)
    runtime = HermesRuntime(config, config.default_user_id)

    if args.command == "chat":
        return _run_chat(runtime, config.default_session_id, args.disable_honcho)
    if args.command == "replay":
        return _run_replay(runtime, config.default_session_id, Path(args.script), args.disable_honcho)
    if args.command == "inspect":
        return _run_inspect(runtime, config.default_session_id)
    if args.command == "tts-spike":
        return _run_tts(config, args.text, args.stem)
    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes local terminal PoC")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--session-id", default=None)
    subparsers = parser.add_subparsers(dest="command")

    chat = subparsers.add_parser("chat", help="Run interactive terminal chat")
    chat.add_argument("--disable-honcho", action="store_true")

    replay = subparsers.add_parser("replay", help="Replay a fixed script")
    replay.add_argument("--script", default="fixtures/replay/daily_stability.json")
    replay.add_argument("--disable-honcho", action="store_true")

    subparsers.add_parser("inspect", help="Inspect config, memory, and latest Honcho output")

    tts = subparsers.add_parser("tts-spike", help="Create one local audio sample with macOS say")
    tts.add_argument("--text", required=True)
    tts.add_argument("--stem", default=None)
    return parser


def _run_chat(runtime: HermesRuntime, session_id: str, disable_honcho: bool) -> int:
    print(f"chat session: {session_id}")
    print("commands: /help /inspect /tts /exit")
    last_reply = ""
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text == "/exit":
            break
        if user_text == "/help":
            print("commands: /help /inspect /tts /exit")
            continue
        if user_text == "/inspect":
            _run_inspect(runtime, session_id)
            continue
        if user_text == "/tts":
            if not last_reply:
                print("no assistant reply yet")
                continue
            client = TTSClient(runtime.config.tts_voice, runtime.config.tts_output_dir)
            output_path = client.synthesize(last_reply, stem=session_id)
            print(f"tts> {output_path}")
            continue

        result = runtime.respond(session_id, user_text, disable_honcho=disable_honcho)
        last_reply = result.text
        print(f"{runtime.character.name}> {result.text}")
        if result.memory_written:
            print(f"[memory] updated {len(result.memory_changes)} item(s)")

    summary_path = runtime.finalize_session(session_id)
    print(f"summary> {summary_path}")
    print(f"transcript> {runtime.transcripts.export_paths(session_id)[1]}")
    return 0


def _run_replay(runtime: HermesRuntime, session_id: str, script_path: Path, disable_honcho: bool) -> int:
    payload = json.loads(script_path.read_text(encoding="utf-8"))
    prompts = payload["prompts"]
    print(f"replay session: {session_id}")
    for index, prompt in enumerate(prompts, start=1):
        print(f"you[{index}]> {prompt}")
        result = runtime.respond(session_id, prompt, disable_honcho=disable_honcho)
        print(f"{runtime.character.name}[{index}]> {result.text}")
    summary_path = runtime.finalize_session(session_id)
    print(f"summary> {summary_path}")
    print(f"transcript> {runtime.transcripts.export_paths(session_id)[1]}")
    return 0


def _run_inspect(runtime: HermesRuntime, session_id: str) -> int:
    state = runtime.inspect(session_id)
    memory = state["memory_state"]
    print(f"project_name: {state['project_name']}")
    print(f"user_id: {state['user_id']}")
    print(f"session_id: {state['session_id']}")
    print(f"character_name: {state['character_name']}")
    print(f"llm_provider: {state['llm_provider']}")
    print(f"llm_model: {state['llm_model']}")
    print(f"character_dir: {state['character_dir']}")
    print(f"memory_markdown_path: {state['memory_markdown_path']}")
    print(f"transcript_markdown_path: {state['transcript_markdown_path']}")
    print(f"recent_turn_count: {state['recent_turn_count']}")
    print(f"relationship_state: {memory.relationship_state}")
    print("profile_facts:")
    for item in memory.profile_facts:
        print(f"  - {item}")
    print("open_threads:")
    for item in memory.open_threads:
        print(f"  - {item}")
    print("latest_honcho:")
    print(state["latest_honcho"])
    return 0


def _run_tts(config, text: str, stem: str | None) -> int:
    client = TTSClient(config.tts_voice, config.tts_output_dir)
    output_path = client.synthesize(text, stem=stem)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
