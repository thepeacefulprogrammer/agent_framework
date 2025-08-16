import os
import json
import subprocess
import tempfile
import re
import difflib
from typing import Any, Optional, Dict, List, Literal
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, validator
from dotenv import load_dotenv

from .tool import tool
from .ctx import context

# Optional external search dependencies
try:
    from ddgs import DDGS  # DuckDuckGo
except Exception:
    DDGS = None

load_dotenv()

BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")
BRAVE_SEARCH_API_WEB_ENDPOINT = os.getenv("BRAVE_SEARCH_API_WEB_ENDPOINT")

BUFFER = 0.05
MAX_QUERY_LENGTH = int(400 * (1 - BUFFER))
MAX_QUERY_WORDS = int(50 * (1 - BUFFER))
MAX_RESULTS = 5

# ------------------------------------------------------------------------------
# Helpers: .agent store and CWD
# ------------------------------------------------------------------------------

AGENT_DIR = ".agent"
PRD_PATH = os.path.join(AGENT_DIR, "prd.json")
TASKS_PATH = os.path.join(AGENT_DIR, "tasks.json")
STOPS_PATH = os.path.join(AGENT_DIR, "stops.json")

_last_tasks_delta: Any = None  # debug aid


def _ensure_agent_dir():
    if not os.path.exists(AGENT_DIR):
        os.makedirs(AGENT_DIR, exist_ok=True)


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        return default


def _write_json(path: str, data: Any):
    _ensure_agent_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _deep_merge(a: Any, b: Any) -> Any:
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    return b


def _resolve_cwd(cwd: Optional[str]) -> str:
    if cwd and isinstance(cwd, str) and cwd.strip():
        return cwd
    return getattr(context, "cwd", ".") or "."


def _join_cwd_path(cwd: str, file_path: str) -> str:
    if os.path.isabs(file_path):
        return file_path
    return os.path.normpath(os.path.join(cwd, file_path))


# ------------------------------------------------------------------------------
# CWD tools
# ------------------------------------------------------------------------------

@tool
def get_cwd() -> dict:
    """Return the current working directory used by tools."""
    return {"cwd": getattr(context, "cwd", os.getcwd())}


@tool
def set_cwd(path: str) -> dict:
    """
    Set the current working directory for subsequent tools.
    Path must exist and be a directory. Recommended to point to the repo root.
    """
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return {"status": "error", "message": f"Path does not exist: {abs_path}"}
    if not os.path.isdir(abs_path):
        return {"status": "error", "message": f"Not a directory: {abs_path}"}
    context.cwd = abs_path
    return {"status": "success", "cwd": abs_path}


# ------------------------------------------------------------------------------
# Core tools (shell, read)
# ------------------------------------------------------------------------------

@tool
def execute_shell_command(command: str, timeout_seconds: int = 120, cwd: Optional[str] = None) -> dict:
    """Execute a shell command with timeout in the current working directory."""
    try:
        workdir = _resolve_cwd(cwd)
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=workdir
        )
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "cwd": workdir
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command timed out"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@tool
def read_file_content(file_path: str, cwd: Optional[str] = None) -> dict:
    """Read and return file contents with metadata (path resolved relative to cwd if not absolute)."""
    try:
        workdir = _resolve_cwd(cwd)
        full_path = _join_cwd_path(workdir, file_path)
        with open(full_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return {
            "status": "success",
            "file_path": full_path,
            "content": content,
            "size": len(content),
            "cwd": workdir
        }
    except FileNotFoundError:
        return {"status": "error", "message": f"File not found: {file_path}"}
    except Exception as e:
        return {"status": "error", "message": f"Error reading file: {str(e)}"}


# ------------------------------------------------------------------------------
# Structured edits (Pydantic) + patch generator
# ------------------------------------------------------------------------------

class FileEdit(BaseModel):
    path: str
    op: Literal["create", "modify", "delete"] = "modify"
    content: str | None = None  # required for create/modify

    @validator("content", always=True)
    def _content_required_for_write(cls, v, values):
        if values.get("op") in ("create", "modify") and (v is None):
            raise ValueError("content is required for create/modify")
        return v


def _normalize_newline(s: str | None) -> str:
    if s is None:
        return ""
    s = s.replace("\r\n", "\n")
    if not s.endswith("\n"):
        s += "\n"
    return s


def _build_unified_diff_for_edit(edit: FileEdit, cwd: str) -> str:
    """
    Create a git-style unified diff for a single edit. We do NOT write to disk here.
    """
    path = edit.path.strip().lstrip("./")
    full_path = _join_cwd_path(cwd, path)
    new_content = _normalize_newline(edit.content)

    if edit.op == "delete":
        old_content = ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except FileNotFoundError:
            old_content = ""
        old_lines = old_content.replace("\r\n", "\n").splitlines(keepends=True)
        new_lines: List[str] = []  # delete -> empty
        header = f"diff --git a/{path} b/{path}\n"
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path}", tofile="/dev/null",
            lineterm="\n"
        )
        body = "".join(diff)
        body = re.sub(r"^\+\+\+ .*", "+++ /dev/null", body, count=1, flags=re.M)
        return header + body

    elif edit.op == "create":
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except FileNotFoundError:
            old_content = ""
        old_lines = old_content.replace("\r\n", "\n").splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        header = f"diff --git a/{path} b/{path}\n"
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile="/dev/null", tofile=f"b/{path}",
            lineterm="\n"
        )
        body = "".join(diff)
        body = re.sub(r"^--- .*", "--- /dev/null", body, count=1, flags=re.M)
        return header + "new file mode 100644\n" + body

    else:  # modify
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except FileNotFoundError:
            old_content = ""
        old_lines = old_content.replace("\r\n", "\n").splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        header = f"diff --git a/{path} b/{path}\n"
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path}", tofile=f"b/{path}",
            lineterm="\n"
        )
        body = "".join(diff)
        return header + body


def _assemble_patch_from_edits(edits: List[FileEdit], cwd: str) -> str:
    parts: List[str] = []
    for e in edits:
        parts.append(_build_unified_diff_for_edit(e, cwd))
        if not parts[-1].endswith("\n"):
            parts[-1] += "\n"
    patch = "\n".join(parts)
    if "@@ " not in patch and "new file mode" not in patch:
        raise ValueError("No unified hunks generated from edits.")
    return patch


def _guess_strip_level(patch: str) -> int:
    return 1 if "diff --git a/" in patch else 0


def _apply_file_edits_impl(
    edits: List[FileEdit],
    mode: Literal["any", "tests_only", "src_only"],
    cwd: Optional[str]
) -> dict:
    """Internal, non-decorated implementation used by tools and wrappers."""
    workdir = _resolve_cwd(cwd)
    # Policy
    changed_paths = [e.path for e in edits]
    if mode == "tests_only":
        bad = [p for p in changed_paths if not (p.startswith("tests/") or os.path.basename(p).startswith("test_"))]
        if bad:
            return {"status": "error", "message": "policy_violation: tests_only", "files": changed_paths}
    if mode == "src_only":
        bad = [p for p in changed_paths if (p.startswith("tests/") or os.path.basename(p).startswith("test_"))]
        if bad:
            return {"status": "error", "message": "policy_violation: src_only", "files": changed_paths}

    try:
        patch_text = _assemble_patch_from_edits(edits, workdir)
    except Exception as e:
        return {"status": "error", "message": f"assemble_patch_failed: {e}"}

    # Persist a debug copy
    try:
        _ensure_agent_dir()
        with open(os.path.join(AGENT_DIR, "last.patch"), "w", encoding="utf-8") as f:
            f.write(patch_text)
    except Exception:
        pass

    patch_path: Optional[str] = None
    try:
        tmp_fd, patch_path = tempfile.mkstemp(suffix=".patch")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(patch_text)

        # git apply
        res = subprocess.run(
            f"git apply --whitespace=nowarn --reject {patch_path}",
            shell=True, cwd=workdir, capture_output=True, text=True, timeout=60
        )
        if res.returncode == 0:
            return {"status": "success", "applied_with": "git", "stdout": res.stdout, "stderr": res.stderr, "cwd": workdir}

        # patch fallback(s)
        p = _guess_strip_level(patch_text)
        for cmd in (f"patch -p{p} < {patch_path}", f"patch -p{1-p} < {patch_path}"):
            res2 = subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, text=True, timeout=60)
            if res2.returncode == 0:
                return {"status": "success", "applied_with": cmd, "stdout": res2.stdout, "stderr": res2.stderr, "cwd": workdir}

        return {
            "status": "error",
            "message": "Failed to apply generated diff",
            "git_stderr": res.stderr,
            "cwd": workdir,
            "first_lines": "\n".join(patch_text.splitlines()[:10])
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Patch apply timed out", "cwd": workdir}
    except Exception as e:
        return {"status": "error", "message": str(e), "cwd": workdir}
    finally:
        try:
            if patch_path and os.path.exists(patch_path):
                os.unlink(patch_path)
        except Exception:
            pass


@tool
def apply_file_edits(
    edits: List[FileEdit],
    mode: Literal["any", "tests_only", "src_only"] = "any",
    cwd: str | None = None
) -> dict:
    """
    Apply file edits described structurally (no raw patch text from the model).
    """
    # Coerce incoming dicts to FileEdit models if needed (tool callers may pass plain dicts)
    edits_models = [e if isinstance(e, FileEdit) else FileEdit.parse_obj(e) for e in edits]
    return _apply_file_edits_impl(edits_models, mode, cwd)


# Wrappers that hard-code policy (avoid depending on model passing mode)
@tool
def apply_file_edits_tests(edits: List[FileEdit], cwd: str | None = None) -> dict:
    """Apply file edits restricted to tests only."""
    edits_models = [e if isinstance(e, FileEdit) else FileEdit.parse_obj(e) for e in edits]
    return _apply_file_edits_impl(edits_models, "tests_only", cwd)


@tool
def apply_file_edits_src(edits: List[FileEdit], cwd: str | None = None) -> dict:
    """Apply file edits restricted to src only (no tests)."""
    edits_models = [e if isinstance(e, FileEdit) else FileEdit.parse_obj(e) for e in edits]
    return _apply_file_edits_impl(edits_models, "src_only", cwd)


# ------------------------------------------------------------------------------
# PRD tools
# ------------------------------------------------------------------------------

def _default_prd() -> dict:
    now = datetime.utcnow().isoformat()
    return {
        "id": "prd-untitled",
        "title": "",
        "overview": "",
        "goals": [],
        "functional_requirements": [],
        "non_goals": [],
        "user_stories": [],
        "success_metrics": [],
        "open_questions": [],
        "context": {"repo": "", "test_runner": "pytest"},
        "created_at": now,
        "updated_at": now
    }


@tool
def prd_get() -> str:
    """Return the PRD JSON as a string (creates a default if none exists)."""
    prd = _read_json(PRD_PATH, _default_prd())
    return json.dumps(prd, indent=2)


@tool
def prd_put(delta_json: str) -> str:
    """
    Merge the provided delta JSON into the PRD and save.
    delta_json: JSON string representing a partial PRD.
    """
    try:
        delta = json.loads(delta_json) if isinstance(delta_json, str) else (delta_json or {})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Invalid delta_json: {e}"})

    prd = _read_json(PRD_PATH, _default_prd())
    merged = _deep_merge(prd, delta)
    merged["updated_at"] = datetime.utcnow().isoformat()
    _write_json(PRD_PATH, merged)
    return json.dumps({"status": "success", "prd": merged}, indent=2)


# ------------------------------------------------------------------------------
# Tasks tools (parents + subtasks)
# ------------------------------------------------------------------------------

def _default_tasks() -> dict:
    now = datetime.utcnow().isoformat()
    return {
        "parents": [],
        "tasks": [],
        "current": {"subtask_id": None},
        "created_at": now,
        "updated_at": now
    }


@tool
def tasks_get() -> str:
    """Return the Tasks JSON store as a string."""
    tasks = _read_json(TASKS_PATH, _default_tasks())
    return json.dumps(tasks, indent=2)


@tool
def tasks_update(delta_json: str) -> str:
    """
    Generic merge (backward compatibility). Prefer tasks_add_parents/subtasks.
    Accepts either a JSON string or a dict. Migrates parent-like entries from tasks[].
    """
    global _last_tasks_delta
    try:
        delta = json.loads(delta_json) if isinstance(delta_json, str) else (delta_json or {})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Invalid delta_json: {e}"})

    _last_tasks_delta = delta  # debug

    store = _read_json(TASKS_PATH, _default_tasks())

    # Merge parents
    if "parents" in delta and isinstance(delta["parents"], list):
        parent_by_id = {p["id"]: p for p in store.get("parents", [])}
        for p in delta["parents"]:
            if "id" not in p:
                p["id"] = f"P-{uuid4().hex[:8]}"
            p.setdefault("status", "PENDING")
            p.setdefault("children", [])
            parent_by_id[p["id"]] = _deep_merge(parent_by_id.get(p["id"], {}), p)
        store["parents"] = list(parent_by_id.values())

    # Merge tasks; migrate parent-like entries to parents
    if "tasks" in delta and isinstance(delta["tasks"], list):
        parent_by_id = {p["id"]: p for p in store.get("parents", [])}
        task_by_id = {t["id"]: t for t in store.get("tasks", [])}
        for t in delta["tasks"]:
            if t.get("parent_id") is None and "children" in t:
                if "id" not in t:
                    t["id"] = f"P-{uuid4().hex[:8]}"
                t.setdefault("status", "PENDING")
                t.setdefault("children", [])
                parent_by_id[t["id"]] = _deep_merge(parent_by_id.get(t["id"], {}), t)
            else:
                if "id" not in t:
                    t["id"] = f"T-{uuid4().hex[:8]}"
                t.setdefault("status", "PENDING")
                task_by_id[t["id"]] = _deep_merge(task_by_id.get(t["id"], {}), t)
        store["parents"] = list(parent_by_id.values())
        store["tasks"] = list(task_by_id.values())

    if "current" in delta and isinstance(delta["current"], dict):
        store["current"] = _deep_merge(store.get("current", {}), delta["current"])

    store["updated_at"] = datetime.utcnow().isoformat()
    _write_json(TASKS_PATH, store)
    return json.dumps({
        "status": "success",
        "received_keys": list(delta.keys()),
        "counts": {"parents": len(store.get("parents", [])), "tasks": len(store.get("tasks", []))},
        "tasks": store
    }, indent=2)


@tool
def tasks_add_parents(parents_json: str) -> str:
    """
    Add or merge parent tasks.
    parents_json: JSON array of {id?, title, description?, status?, children?}
    """
    try:
        lst = json.loads(parents_json) if isinstance(parents_json, str) else (parents_json or [])
        if isinstance(lst, dict) and "parents" in lst:
            lst = lst["parents"]
        if not isinstance(lst, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Invalid parents_json: {e}"})

    store = _read_json(TASKS_PATH, _default_tasks())
    parent_by_id = {p["id"]: p for p in store.get("parents", [])}

    added = 0
    for p in lst:
        if "title" not in p or not p["title"]:
            return json.dumps({"status": "error", "message": "Each parent must have a title"})
        pid = p.get("id") or f"P-{uuid4().hex[:8]}"
        p["id"] = pid
        p.setdefault("status", "PENDING")
        p.setdefault("children", [])
        parent_by_id[pid] = _deep_merge(parent_by_id.get(pid, {}), p)
        added += 1

    store["parents"] = list(parent_by_id.values())
    store["updated_at"] = datetime.utcnow().isoformat()
    _write_json(TASKS_PATH, store)
    return json.dumps({"status": "success", "added": added, "counts": {"parents": len(store["parents"])}, "tasks": store}, indent=2)


@tool
def tasks_add_subtasks(subtasks_json: str) -> str:
    """
    Add or merge subtasks.
    subtasks_json: JSON array of {id?, parent_id, title, kind, status?, test_cmd?, relevant_files?, notes?}
    """
    try:
        lst = json.loads(subtasks_json) if isinstance(subtasks_json, str) else (subtasks_json or [])
        if isinstance(lst, dict) and "tasks" in lst:
            lst = lst["tasks"]
        if not isinstance(lst, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Invalid subtasks_json: {e}"})

    store = _read_json(TASKS_PATH, _default_tasks())

    parent_ids = {p["id"] for p in store.get("parents", [])}

    task_by_id = {t["id"]: t for t in store.get("tasks", [])}
    added = 0
    for t in lst:
        if not t.get("parent_id"):
            return json.dumps({"status": "error", "message": "Each subtask must include parent_id"})
        if parent_ids and t["parent_id"] not in parent_ids:
            pass  # allow but could warn
        tid = t.get("id") or f"T-{uuid4().hex[:8]}"
        t["id"] = tid
        t.setdefault("status", "PENDING")
        task_by_id[tid] = _deep_merge(task_by_id.get(tid, {}), t)
        added += 1

    store["tasks"] = list(task_by_id.values())
    store["updated_at"] = datetime.utcnow().isoformat()
    _write_json(TASKS_PATH, store)
    return json.dumps({
        "status": "success", "added": added,
        "counts": {"tasks": len(store["tasks"])},
        "tasks": store
    }, indent=2)


@tool
def tasks_get_next() -> str:
    """
    Select the next actionable subtask.
    Heuristic: first task with status PENDING AND has 'parent_id' (i.e., it’s a subtask).
    Sets current.subtask_id and returns it.
    """
    store = _read_json(TASKS_PATH, _default_tasks())

    candidates = [t for t in store.get("tasks", []) if t.get("status") == "PENDING" and t.get("parent_id")]
    next_task = candidates[0] if candidates else None

    if not next_task:
        store["current"]["subtask_id"] = None
        store["updated_at"] = datetime.utcnow().isoformat()
        _write_json(TASKS_PATH, store)
        return json.dumps({"status": "done", "message": "No pending subtasks."})

    store["current"]["subtask_id"] = next_task["id"]
    store["updated_at"] = datetime.utcnow().isoformat()
    _write_json(TASKS_PATH, store)

    hint = "red" if not next_task.get("test_cmd") else "check"
    return json.dumps({"status": "success", "subtask": next_task, "hint": hint}, indent=2)


@tool
def tasks_get_next_decision() -> str:
    """
    Pick next actionable subtask (must have parent_id and PENDING), set current,
    then classify its test_cmd by running it:
      - classification: 'missing' (no test_cmd or rc in {4,5} or 'file not found'/'no tests ran')
                        'fail' (rc == 1)
                        'pass' (rc == 0)
      - recommend: 'red' | 'green' | 'refactor'
    """
    store = _read_json(TASKS_PATH, _default_tasks())

    candidates = [t for t in store.get("tasks", []) if t.get("status") == "PENDING" and t.get("parent_id")]
    next_task = candidates[0] if candidates else None
    if not next_task:
        store["current"]["subtask_id"] = None
        store["updated_at"] = datetime.utcnow().isoformat()
        _write_json(TASKS_PATH, store)
        return json.dumps({"status": "done", "message": "No pending subtasks."})

    store["current"]["subtask_id"] = next_task["id"]
    store["updated_at"] = datetime.utcnow().isoformat()
    _write_json(TASKS_PATH, store)

    workdir = _resolve_cwd(None)
    test_cmd = next_task.get("test_cmd") or ""
    if not test_cmd.strip():
        return json.dumps({"status": "success", "subtask": next_task, "classification": "missing", "recommend": "red"}, indent=2)

    try:
        res = subprocess.run(test_cmd, shell=True, capture_output=True, text=True, timeout=120, cwd=workdir)
        rc = res.returncode
        stderr = (res.stderr or "")[:500]
        stdout = (res.stdout or "")[:500]
        if rc == 1:
            classification = "fail"
            recommend = "green"
        elif rc == 0:
            classification = "pass"
            recommend = "refactor"
        else:
            if "file or directory not found" in stderr.lower() or "no tests ran" in stdout.lower():
                classification = "missing"
                recommend = "red"
            else:
                classification = "missing"
                recommend = "red"
        return json.dumps({
            "status": "success",
            "subtask": next_task,
            "rc": rc,
            "classification": classification,
            "recommend": recommend,
            "stderr_snippet": stderr,
            "stdout_snippet": stdout
        }, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "message": "test_cmd timeout", "subtask": next_task}, indent=2)


@tool
def tasks_last_delta() -> str:
    """Debug: return last parsed delta passed to tasks_update."""
    return json.dumps({"last_delta": _last_tasks_delta}, indent=2)


# ------------------------------------------------------------------------------
# Stop/Q&A tool
# ------------------------------------------------------------------------------

@tool
def stop_request(payload_json: str) -> str:
    """
    Open a stop/Q&A ticket and pause the graph.
    """
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Invalid payload_json: {e}"})

    stops = _read_json(STOPS_PATH, {"tickets": []})
    ticket = {
        "id": f"S-{len(stops.get('tickets', [])) + 1}",
        "status": "OPEN",
        "created_at": datetime.utcnow().isoformat(),
        **payload,
    }
    stops.setdefault("tickets", []).append(ticket)
    _write_json(STOPS_PATH, stops)

    # Pause the graph
    context.running = False
    return json.dumps({"status": "paused", "ticket": ticket}, indent=2)


# ------------------------------------------------------------------------------
# Synchronous console Q&A tool
# ------------------------------------------------------------------------------

@tool
def ask_user(question: str, options: Optional[List[str]] = None, allow_free_text: bool = True, default: Optional[str] = None) -> dict:
    """
    Prompt the user on the console and return the answer to the model.
    """
    try:
        print("\n[Q&A] " + question)
        selected_index = None
        if options:
            for i, opt in enumerate(options, 1):
                print(f"  {i}) {opt}")
        raw = input("Your answer: ").strip()
        if not raw and default is not None:
            return {"answer": default, "selected_index": None}

        if options and raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                selected_index = idx
                return {"answer": options[idx - 1], "selected_index": idx}

        if not raw and allow_free_text and default is not None:
            return {"answer": default, "selected_index": None}
        return {"answer": raw, "selected_index": selected_index}
    except EOFError:
        return {"error": "No stdin available"}
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------------------------
# Optional Search tool
# ------------------------------------------------------------------------------

@tool
def search(query: str, max_results: int = MAX_RESULTS) -> str:
    """
    Unified web search (DDG + optional Brave).
    """
    q = _normalize_query(query)
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    if DDGS is not None:
        try:
            for i, r in enumerate(DDGS().text(q, max_results=max_results)):
                results.append({
                    "url": r.get("href"),
                    "title": r.get("title"),
                    "description": r.get("body"),
                    "engine": "ddg",
                    "rank": i + 1
                })
        except Exception as e:
            errors.append(f"ddg: {e}")

    if BRAVE_SEARCH_API_KEY and BRAVE_SEARCH_API_WEB_ENDPOINT:
        try:
            import requests
            resp = requests.get(
                BRAVE_SEARCH_API_WEB_ENDPOINT,
                params={"q": q, "search_lang": "en", "count": str(max_results), "summary": "true"},
                headers={"X-Subscription-Token": BRAVE_SEARCH_API_KEY, "Accept": "application/json", "Accept-Encoding": "gzip"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                web = (data or {}).get("web", {})
                rlist = web.get("results", []) or []
                for i, r in enumerate(rlist[:max_results]):
                    results.append({
                        "url": r.get("url"),
                        "title": r.get("title"),
                        "description": r.get("description"),
                        "engine": "brave",
                        "rank": i + 1
                    })
            else:
                errors.append(f"brave http {resp.status_code}")
        except Exception as e:
            errors.append(f"brave: {e}")

    # Dedup by URL
    dedup: Dict[str, Dict[str, Any]] = {}
    for it in results:
        url = it.get("url")
        if not url:
            continue
        if url in dedup:
            prev = dedup[url]
            prev["engine"] = "+".join(sorted(set(prev.get("engine", "").split("+")) | {it.get("engine", "")}))
            prev["rank"] = min(prev.get("rank", 999), it.get("rank", 999))
            if not prev.get("title") and it.get("title"):
                prev["title"] = it["title"]
            if not prev.get("description") and it.get("description"):
                prev["description"] = it["description"]
        else:
            dedup[url] = it

    merged = sorted(list(dedup.values()), key=lambda x: (x.get("rank", 999), 0 if "brave" in x.get("engine", "") else 1))
    return json.dumps({"query": q, "results": merged[:max_results], "errors": errors}, indent=2)


def _normalize_query(q: str) -> str:
    q = q.strip()
    if len(q) > MAX_QUERY_LENGTH:
        q = q[:MAX_QUERY_LENGTH - 3] + "..."
    words = q.split()
    if len(words) > MAX_QUERY_WORDS:
        q = " ".join(words[:MAX_QUERY_WORDS - 1]) + "..."
    return q

# --- Filesystem listing (avoid read_file_content on directories) ---
@tool
def list_directory(path: str = ".", cwd: Optional[str] = None) -> dict:
    """
    List directory entries with minimal metadata.
    Returns: {status, cwd, path, entries:[{name, type:'file'|'dir'|'other', size}]}
    """
    workdir = _resolve_cwd(cwd)
    full = _join_cwd_path(workdir, path)
    try:
        entries = []
        for name in os.listdir(full):
            p = os.path.join(full, name)
            if os.path.isdir(p):
                t = "dir"
                size = 0
            elif os.path.isfile(p):
                t = "file"
                try:
                    size = os.path.getsize(p)
                except Exception:
                    size = 0
            else:
                t = "other"
                size = 0
            entries.append({"name": name, "type": t, "size": size})
        return {"status": "success", "cwd": workdir, "path": full, "entries": entries}
    except Exception as e:
        return {"status": "error", "message": str(e), "cwd": workdir, "path": full}

# --- Run pytest deterministically (classify outcome) ---
@tool
def run_pytest(expr: Optional[str] = None, cwd: Optional[str] = None, timeout_seconds: int = 300) -> dict:
    """
    Run pytest -q [expr].
    Returns: {status, rc, classification:'pass'|'fail'|'missing'|'error', stdout, stderr}
    - pass => rc==0
    - fail => rc==1 (assertion failures)
    - missing => rc in {4,5} or stderr/stdout indicates missing tests
    - error => other rc values
    """
    workdir = _resolve_cwd(cwd)
    cmd = f"pytest -q {expr}" if expr else "pytest -q"
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_seconds, cwd=workdir)
        rc = res.returncode
        out = (res.stdout or "")
        err = (res.stderr or "")
        if rc == 0:
            cls = "pass"
        elif rc == 1:
            cls = "fail"
        elif rc in (4, 5) or "file or directory not found" in err.lower() or "no tests ran" in out.lower():
            cls = "missing"
        else:
            cls = "error"
        return {"status": "success", "rc": rc, "classification": cls, "stdout": out, "stderr": err, "cwd": workdir}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "pytest timeout", "cwd": workdir}
    except Exception as e:
        return {"status": "error", "message": str(e), "cwd": workdir}

# --- Git commit helper (handles init if needed) ---
@tool
def git_commit(message: str, allow_init: bool = True, cwd: Optional[str] = None) -> dict:
    """
    Stage all changes and commit with the provided message.
    - If not in a git repo and allow_init=True, initializes repo and sets a minimal user config.
    Returns: {status, repo_initialized, commit_hash?, stdout, stderr}
    """
    workdir = _resolve_cwd(cwd)

    def _run(cmd: str, timeout: int = 60):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=workdir)

    try:
        # Detect repo
        res = _run("git rev-parse --is-inside-work-tree")
        in_repo = (res.returncode == 0 and "true" in res.stdout.strip().lower())

        repo_initialized = False
        if not in_repo:
            if not allow_init:
                return {"status": "error", "message": "Not a git repo", "cwd": workdir}
            # Initialize
            _run("git init")
            # Basic user config (ensure commits succeed)
            _run('git config user.name "Repo Bot"')
            _run('git config user.email "bot@example.com"')
            repo_initialized = True

        # Stage and commit
        add_res = _run("git add -A")
        if add_res.returncode != 0:
            return {"status": "error", "message": "git add failed", "stderr": add_res.stderr, "cwd": workdir}

        # Check if anything to commit
        diff_res = _run("git diff --cached --quiet")
        if diff_res.returncode == 0:
            # nothing staged
            return {"status": "noop", "message": "Nothing to commit", "repo_initialized": repo_initialized, "cwd": workdir}

        commit_res = _run(f"git commit -m {json.dumps(message)}")
        if commit_res.returncode != 0:
            return {"status": "error", "message": "git commit failed", "stderr": commit_res.stderr, "cwd": workdir}

        rev_res = _run("git rev-parse --short HEAD")
        commit_hash = rev_res.stdout.strip() if rev_res.returncode == 0 else None

        return {
            "status": "success",
            "repo_initialized": repo_initialized,
            "commit_hash": commit_hash,
            "stdout": commit_res.stdout,
            "cwd": workdir
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "git operation timeout", "cwd": workdir}
    except Exception as e:
        return {"status": "error", "message": str(e), "cwd": workdir}


# --- Task state helpers (mark done, compute progress) ---
@tool
def tasks_mark_done(subtask_id: Optional[str] = None) -> str:
    """
    Mark a subtask DONE. If subtask_id is None, uses tasks.current.subtask_id.
    If all subtasks under the same parent are DONE, mark the parent as DONE.
    """
    store = _read_json(TASKS_PATH, _default_tasks())
    sid = subtask_id or (store.get("current") or {}).get("subtask_id")
    if not sid:
        return json.dumps({"status": "error", "message": "No subtask_id provided and no current subtask"}, indent=2)

    tasks = store.get("tasks", [])
    t = next((x for x in tasks if x.get("id") == sid), None)
    if not t:
        return json.dumps({"status": "error", "message": f"Subtask {sid} not found"}, indent=2)

    t["status"] = "DONE"
    parent_id = t.get("parent_id")

    # If all subtasks for this parent are DONE, mark parent DONE
    if parent_id:
        siblings = [x for x in tasks if x.get("parent_id") == parent_id]
        all_done = all(x.get("status") == "DONE" for x in siblings) if siblings else False
        if all_done:
            parents = store.get("parents", [])
            p = next((p for p in parents if p.get("id") == parent_id), None)
            if p:
                p["status"] = "DONE"
            store["parents"] = parents

    store["tasks"] = tasks
    store["updated_at"] = datetime.utcnow().isoformat()
    _write_json(TASKS_PATH, store)
    return json.dumps({"status": "success", "subtask_id": sid, "parent_id": parent_id, "tasks": store}, indent=2)


@tool
def tasks_progress() -> str:
    """
    Return a summary of task counts: {parents:{PENDING,DONE}, tasks:{PENDING,IN_PROGRESS,DONE}}
    """
    store = _read_json(TASKS_PATH, _default_tasks())
    parents = store.get("parents", [])
    tasks = store.get("tasks", [])

    def counts(items: List[dict]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for it in items:
            st = it.get("status", "PENDING")
            out[st] = out.get(st, 0) + 1
        return out

    return json.dumps({
        "status": "success",
        "parents": counts(parents),
        "tasks": counts(tasks),
        "current": store.get("current", {})
    }, indent=2)

@tool
def ensure_pytest(cwd: Optional[str] = None, timeout_seconds: int = 300) -> dict:
    """
    Ensure 'pytest' is available in the current environment.
    - Tries 'pytest --version'.
    - If missing, runs: python -m pip install pytest.
    """
    workdir = _resolve_cwd(cwd)
    try:
        res = subprocess.run("pytest --version", shell=True, capture_output=True, text=True, timeout=30, cwd=workdir)
        if res.returncode == 0:
            return {"status": "success", "installed": True, "message": "pytest already installed"}
        ins = subprocess.run("python -m pip install pytest", shell=True, capture_output=True, text=True, timeout=timeout_seconds, cwd=workdir)
        if ins.returncode == 0:
            return {"status": "success", "installed": True, "message": "pytest installed"}
        return {"status": "error", "installed": False, "stderr": ins.stderr}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "ensure_pytest timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

import ast

@tool
def inspect_test_quality(file_path: str, mode: Literal["behavior", "scaffold"] = "behavior", cwd: Optional[str] = None) -> dict:
    """
    Inspect a test file for minimal quality:
    - Rejects trivial failure patterns (assert False, pytest.fail, raising AssertionError)
    - Requires at least one non-trivial assert (not a bare constant)
    - behavior mode: requires import from project code (e.g., 'snake_game' or 'src.')
    - scaffold mode: allows filesystem structure asserts (e.g., os.path.exists) but still no trivial failure

    Returns: { ok: bool, issues: [str], stats: {...} }
    """
    workdir = _resolve_cwd(cwd)
    full_path = _join_cwd_path(workdir, file_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
    except FileNotFoundError:
        return {"ok": False, "issues": [f"File not found: {file_path}"], "stats": {}}

    issues: List[str] = []
    stats: Dict[str, Any] = {"assert_count": 0, "trivial_asserts": 0, "imports": [], "has_fs_checks": False}

    # Cheap textual checks for trivial failure patterns
    lowered = source.lower()
    if "assert false" in lowered or "pytest.fail(" in lowered or "raise assertionerror" in lowered:
        issues.append("Trivial failure pattern detected (assert False / pytest.fail / raise AssertionError).")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        return {"ok": False, "issues": [f"Syntax error: {e}"], "stats": {}}

    # Walk AST for imports and asserts
    allowed_import_prefixes = ("snake_game", "src")
    stdlib_like = {"os", "sys", "pathlib", "json", "time", "re", "typing", "pytest"}

    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                stats["imports"].append(alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            mod = node.module or ""
            stats["imports"].append(mod)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            # detect os.path.exists(...) or Path(...).exists()
            try:
                if isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                    if attr == "exists":
                        stats["has_fs_checks"] = True
                    elif isinstance(node.func.value, ast.Attribute):
                        if getattr(node.func.value, "attr", "") == "path" and getattr(node.func.value.value, "id", "") == "os":
                            if getattr(node.func, "attr", "") == "exists":
                                stats["has_fs_checks"] = True
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "exists":
                    stats["has_fs_checks"] = True
            except Exception:
                pass
            self.generic_visit(node)

        def visit_Assert(self, node: ast.Assert):
            stats["assert_count"] += 1
            # Trivial assert if test expression is a bare constant (True/False/None or literal)
            trivial = isinstance(node.test, ast.Constant) or isinstance(node.test, ast.NameConstant)
            # Also treat compare with a constant True as trivial (rare)
            if isinstance(node.test, ast.Compare) and any(isinstance(c, ast.Constant) for c in node.test.comparators):
                # still can be meaningful; don't mark as trivial unless it's exactly True/False alone
                pass
            if trivial:
                stats["trivial_asserts"] += 1
            self.generic_visit(node)

    Visitor().visit(tree)

    # Quality rules
    if stats["assert_count"] == 0:
        issues.append("No asserts found.")
    if stats["trivial_asserts"] > 0:
        issues.append("Contains trivial asserts (e.g., bare constants).")
    if mode == "behavior":
        # Must import project code (not just stdlib/pytest)
        imported = set(stats["imports"])
        has_proj_import = any((imp.startswith(allowed_import_prefixes)) for imp in imported)
        if not has_proj_import:
            # Heuristic: block tests that don't import project code at all
            # (You can relax this if you prefer)
            issues.append("Behavior test does not import project code (expected import from 'snake_game' or 'src').")
    elif mode == "scaffold":
        # Allow filesystem checks, but still forbid trivial failure
        if not stats["has_fs_checks"]:
            issues.append("Scaffold test should check repository structure (e.g., os.path.exists).")

    ok = len(issues) == 0
    return {"ok": ok, "issues": issues, "stats": stats, "path": file_path}
