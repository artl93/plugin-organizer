#!/usr/bin/env python3
"""
Run an AI tool to generate an updated plugin_mapping JSON.
"""

import argparse
import json
import selectors
import shutil
import subprocess
import time
from typing import TextIO, cast
from pathlib import Path


TOOL_ORDER = ["copilot", "claude", "codex", "opencode"]


def log(message: str) -> None:
    print(f"[ai] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate plugin_mapping.json with an AI tool.",
    )
    parser.add_argument(
        "--input",
        default="./reports/au-plugins.json",
        help="Path to the JSON export for AI input.",
    )
    parser.add_argument(
        "--prompt",
        default=str(Path(__file__).with_name("prompts") / "plugin_mapping_prompt.md"),
        help="Path to the prompt template.",
    )
    parser.add_argument(
        "--output",
        default="./plugin_mapping.generated.json",
        help="Path to write the generated mapping JSON.",
    )
    parser.add_argument(
        "--tool",
        default=None,
        help="Force a specific tool (claude/copilot/codex/opencode).",
    )
    return parser.parse_args()


def load_prompt(prompt_path: Path, input_path: Path) -> str:
    prompt = prompt_path.read_text(encoding="utf-8")
    input_json = input_path.read_text(encoding="utf-8")
    return prompt.replace("{{INPUT_JSON}}", input_json)


def extract_json(output: str) -> dict:
    start = output.find("{")
    end = output.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in output.")
    snippet = output[start : end + 1]
    return json.loads(snippet)


def save_raw_output(output: str, tool: str) -> Path:
    reports_dir = Path("./reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / f"ai-output-{tool}.txt"
    output_path.write_text(output, encoding="utf-8")
    return output_path


def run_tool_streaming(command: list[str], prompt: str) -> tuple[int, str, str]:
    """Run an AI tool with streaming output.
    
    Uses select-based streaming for progress updates, with fallback to
    communicate() if streaming encounters errors.
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except BrokenPipeError:
        log("Warning: Broken pipe while writing prompt")
        # Process may have exited early, continue to read output

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    selector.register(process.stderr, selectors.EVENT_READ)

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_bytes = 0
    last_report = time.time()

    def report_progress(force: bool = False) -> None:
        nonlocal last_report
        now = time.time()
        if force or now - last_report >= 1.0:
            log(f"Streaming output: {stdout_bytes} bytes")
            last_report = now

    try:
        while selector.get_map():
            events = selector.select(timeout=0.1)
            for key, _ in events:
                stream = cast(TextIO, key.fileobj)
                try:
                    line = stream.readline()
                    if not line:
                        selector.unregister(stream)
                        continue
                    if stream is process.stdout:
                        stdout_chunks.append(line)
                        stdout_bytes += len(line.encode("utf-8"))
                        print(line, end="", flush=True)
                    else:
                        stderr_chunks.append(line)
                        log(line.rstrip())
                    report_progress()
                except (IOError, OSError) as e:
                    log(f"Warning: IO error reading stream: {e}")
                    try:
                        selector.unregister(stream)
                    except (KeyError, ValueError):
                        pass

            if process.poll() is not None and not selector.get_map():
                break
    except Exception as e:
        log(f"Warning: Streaming error: {e}")
    finally:
        selector.close()

    # Drain any remaining output
    try:
        remaining_stdout, remaining_stderr = process.communicate(timeout=10)
        if remaining_stdout:
            stdout_chunks.append(remaining_stdout)
            print(remaining_stdout, end="", flush=True)
        if remaining_stderr:
            stderr_chunks.append(remaining_stderr)
    except subprocess.TimeoutExpired:
        process.kill()
        log("Warning: Process timed out, killed")
    except Exception as e:
        log(f"Warning: Error draining output: {e}")

    report_progress(force=True)
    return process.returncode or 0, "".join(stdout_chunks), "".join(stderr_chunks)


def tool_commands(tool: str) -> list[list[str]]:
    if tool == "claude":
        return [["claude"]]
    if tool == "copilot":
        return [["copilot"], ["gh", "copilot", "suggest"]]
    if tool == "codex":
        return [["codex"], ["openai", "codex"]]
    if tool == "opencode":
        return [["opencode"]]
    return []


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser()
    prompt_path = Path(args.prompt).expanduser()
    output_path = Path(args.output).expanduser()

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")
    if not prompt_path.exists():
        raise SystemExit(f"Prompt not found: {prompt_path}")

    log(f"Loading prompt from {prompt_path}")
    log(f"Loading input JSON from {input_path}")
    prompt = load_prompt(prompt_path, input_path)
    log(f"Prompt size: {len(prompt)} chars")

    available_tools = TOOL_ORDER
    if args.tool:
        available_tools = [args.tool]

    log(f"Tool priority: {', '.join(available_tools)}")

    for tool in available_tools:
        if tool not in TOOL_ORDER:
            continue
        log(f"Checking tool: {tool}")
        if shutil.which(tool) is None and tool != "copilot":
            log(f"Tool not found: {tool}")
            continue
        if (
            tool == "copilot"
            and shutil.which("copilot") is None
            and shutil.which("gh") is None
        ):
            log("Tool not found: copilot or gh")
            continue

        for command in tool_commands(tool):
            if shutil.which(command[0]) is None:
                continue
            log(f"Attempting command: {' '.join(command)}")
            log(f"Running {tool} with command: {' '.join(command)}")
            exit_code, stdout_text, stderr_text = run_tool_streaming(command, prompt)
            if exit_code != 0:
                log(f"Command failed (exit {exit_code})")
                if stderr_text:
                    log(stderr_text.strip())
                continue
            log(f"Raw output size: {len(stdout_text)} chars")
            raw_path = save_raw_output(stdout_text, tool)
            log(f"Saved raw output to {raw_path}")
            try:
                mapping = extract_json(stdout_text)
            except Exception as exc:
                log(f"Failed to parse JSON output: {exc}")
                continue

            log(f"Parsed JSON keys: {', '.join(sorted(mapping.keys()))}")

            output_path.write_text(
                json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8"
            )
            log(f"Wrote {output_path}")
            return

    log("No AI tool succeeded. Please run manually with the prompt.")
    log(f"Prompt: {prompt_path}")
    log(f"Input: {input_path}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
