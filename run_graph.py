import logging
import json
import os
import subprocess
import argparse
import signal
from dotenv import load_dotenv

from src.minimal_agent_framework import Graph, Node, EventEmitter, context
from src.minimal_agent_framework.tool import ToolRegistry
from src.minimal_agent_framework.utils import call_llm

# Ensure tools are registered by importing the module that defines them
from src.minimal_agent_framework import maf_tools  # noqa: F401

logging.basicConfig(level=logging.INFO)
for name in ("httpx", "httpcore"):
    logging.getLogger(name).setLevel(logging.ERROR)

load_dotenv()

def load_prd() -> dict:
    try:
        s = ToolRegistry.call("prd_get", {})
        if isinstance(s, str):
            return json.loads(s)
        if isinstance(s, dict):
            return s
    except Exception as e:
        logging.warning(f"load_prd failed: {e}")
    return {}

def save_prd(prd: dict) -> None:
    try:
        ToolRegistry.call("prd_put", {"delta_json": json.dumps(prd)})
    except Exception as e:
        logging.warning(f"save_prd failed: {e}")


# ----------------------------
# Event handlers (console UX)
# ----------------------------
def text_handler(x: str):
    print(f"{x}", end='', flush=True)

def tool_call_handler(x: str):
    print(f"\n🛠️  Tool Called: {x}\n")

def tool_result_handler(x: dict):
    try:
        name = x.get("name")
        result = x.get("result")
        preview = json.dumps(result)[:400] if isinstance(result, (dict, list)) else str(result)[:400]
        print(f"Tool result ({name}): {preview}\n")
    except Exception:
        print(f"Tool result: {x}\n")

def error_handler(x: str):
    print(f"Error raised: {x}")

# ----------------------------
# Repo root / CWD helpers
# ----------------------------
def detect_repo_root(start_path: str) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            root = res.stdout.strip()
            if os.path.isdir(root):
                return root
    except Exception:
        pass
    return start_path

def seed_cwd(cli_cwd: str | None):
    base = cli_cwd if cli_cwd else os.getenv("AGENT_REPO_DIR") or os.getcwd()
    repo_root = detect_repo_root(base)
    context.cwd = repo_root
    print(f"Using context.cwd = {context.cwd}")

# ----------------------------
# STOP ticket and store helpers
# ----------------------------
AGENT_DIR = ".agent"
STOPS_PATH = os.path.join(AGENT_DIR, "stops.json")
TASKS_PATH = os.path.join(AGENT_DIR, "tasks.json")
PRD_PATH = os.path.join(AGENT_DIR, "prd.json")

def _read_json(path: str, default: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def handle_open_stops() -> bool:
    """
    If there is an OPEN stop ticket, prompt the user for answers,
    write them into PRD context, close the ticket, and return True (handled).
    """
    stops = _read_json(STOPS_PATH, {"tickets": []})
    tickets = stops.get("tickets", [])
    open_tickets = [t for t in tickets if t.get("status") == "OPEN"]
    if not open_tickets:
        return False

    t = open_tickets[-1]
    print("\n=== STOP REQUEST ===")
    print(f"Reason: {t.get('reason')}")
    answers = {}
    questions = t.get("questions", [])
    options = t.get("options", {})
    for q in questions:
        print("\n" + q)
        opts = options.get(q)
        if isinstance(opts, list) and opts:
            for i, opt in enumerate(opts, 1):
                print(f"  {i}) {opt}")
        try:
            ans = input("Your answer: ").strip()
        except EOFError:
            ans = ""
        answers[q] = ans

    # Persist answers into PRD context
    prd = load_prd()
    ctx = prd.get("context", {})
    ctx.setdefault("qna_answers", []).append({"ticket_id": t.get("id"), "answers": answers})
    prd["context"] = ctx
    save_prd(prd)

    # Close ticket
    for i, ticket in enumerate(tickets):
        if ticket.get("id") == t.get("id"):
            tickets[i]["status"] = "CLOSED"
            break
    stops["tickets"] = tickets
    _write_json(STOPS_PATH, stops)
    print("=== RESUMING ===\n")
    return True

# ----------------------------
# Ctrl+C pause → model console
# ----------------------------
def on_sigint(signum, frame):
    print("\n[Pause] Ctrl+C detected. Pausing after current operation...")
    context.paused = True
    context.running = False

signal.signal(signal.SIGINT, on_sigint)

def model_console():
    """
    Ad-hoc model Q&A while paused.
    - Uses current context (cwd, PRD/tasks info).
    - No tools and no routing.
    - Blank line to resume.
    """
    print("\n--- Model console ---")
    print("Type a question for the model. Blank line to resume.")
    saved_response_id = getattr(context, "response_id", None)
    try:
        while True:
            try:
                q = input("model> ").strip()
            except EOFError:
                q = ""
            if not q:
                break

            instructions = (
                "Out-of-band user query during a paused run. "
                "Use the current context (PRD, tasks, cwd) if relevant. "
                "Do not call tools. Do not route. Keep the answer concise."
            )
            context.response_id = None  # isolate console conversation
            call_llm(q, instructions=instructions, tools=[], tool_choice=None, max_round_trips=2)
    finally:
        context.response_id = saved_response_id
    print("--- Resuming graph ---\n")

# ----------------------------
# Build graph and nodes
# ----------------------------
def build_graph():
    graph = Graph()

    events = EventEmitter()
    events.on("text", text_handler)
    events.on("tool_call", tool_call_handler)
    events.on("tool_result", tool_result_handler)
    events.on("error", error_handler)
    context.events = events

    # Ensure cwd is set
    if not getattr(context, "cwd", None):
        seed_cwd(None)

    # Nodes
    qna_iterate = (Node()
        .name("QnA.Iterate")
        .tools(["ask_user", "prd_put"])
        .instructions(
            "You are in the Q&A stage. Ask 2–5 concise, multiple-choice questions using the ask_user tool. "
            "Stop as soon as clarity is reached (problem, goals, primary user, acceptance sketch). "
            "Summarize understanding in ≤5 bullets. Update PRD context via prd_put as needed."
        )
        .input("Begin Q&A to clarify the task. Keep it tight. Use ask_user for each question.")
        .budget(10)
    )

    worktype_decide = (Node()
        .name("WorkType.Decide")
        .tools([])
        .instructions(
            "Decide the nature of the work based on the Q&A context: one of {coding, research, docs}. "
            "Briefly justify your choice in one sentence."
        )
        .input("Classify work type.")
        .budget(3)
    )

    prd_draft = (Node()
        .name("PRD.Draft")
        .tools(["prd_put"])
        .instructions(
            "Draft or update the PRD JSON using prd_put with fields: title, overview, goals, functional_requirements, "
            "non_goals, user_stories, success_metrics, open_questions, context. Keep it minimal and clear."
        )
        .input("Create or update the PRD based on Q&A clarity.")
        .budget(4)
    )

    plan_review = (Node()
        .name("Plan.Review")
        .tools(["prd_get", "read_file_content", "execute_shell_command", "search"])
        .instructions(
            "Sanity-check the PRD: ensure each functional requirement has at least one acceptance idea "
            "(a test_cmd candidate or measurable criterion). Infer test runner. "
            "If a decision is needed, you may either use ask_user (if available) or stop_request."
        )
        .input("Review and refine the PRD. Be concise.")
        .budget(8)
    )

    # Node: Tasks.ParentPlan
    tasks_parent = (Node()
        .name("Tasks.ParentPlan")
        .tools(["prd_get", "tasks_add_parents", "tasks_get"])
        .instructions(
            "Create ~5 high-level parent tasks that cover the PRD's functional requirements.\n"
            "- Call tasks_add_parents with a JSON array of parents in this shape:\n"
            "  [ {\"id\": \"P-setup\"?, \"title\": \"...\", \"description\": \"...\"?, \"status\": \"PENDING\"? }, ... ]\n"
            "- After adding, call tasks_get and verify parents length >= 1 before routing."
        )
        .input("Generate parent tasks.")
        .budget(4)
    )

    # Node: Tasks.Subtasks
    tasks_subtasks = (Node()
        .name("Tasks.Subtasks")
        .tools(["prd_get", "tasks_get", "tasks_add_subtasks", "execute_shell_command"])
        .instructions(
            "For each parent, create actionable subtasks with TDD intent.\n"
            "- Each subtask must include: parent_id, title, kind ('build'|'fix'|'refactor'|'docs'|'research'), status='PENDING' (default).\n"
            "- Include test_cmd if known (e.g., 'pytest -q ::tests/test_core.py::test_tick').\n"
            "- Call tasks_add_subtasks with a JSON array of subtasks:\n"
            "  [ {\"parent_id\": \"P-setup\", \"title\": \"Scaffold repo\", \"kind\": \"build\", \"test_cmd\": null, \"relevant_files\": [\"README.md\"] }, ... ]\n"
            "- After adding, call tasks_get and verify tasks length >= 1 before routing."
        )
        .input("Expand parents into subtasks.")
        .budget(6)
    )


    tasks_select = (Node()
        .name("Tasks.SelectNext")
        .tools(["tasks_get_next_decision"])
        .instructions(
            "Call tasks_get_next_decision. It returns 'recommend': red|green|refactor.\n"
            "- Route to Implement.Red if recommend=='red'\n"
            "- Route to Implement.Green if recommend=='green'\n"
            "- Route to Implement.Refactor if recommend=='refactor'\n"
            "- If status=='done', route to Done."
        )
        .input("Pick the next subtask and route based on the recommendation.")
        .budget(6)
    )


    def pre_set_current_task_context():
        store = _read_json(TASKS_PATH, {"current": {"subtask_id": None}, "tasks": []})
        sub_id = store.get("current", {}).get("subtask_id")
        context.subtask_id = sub_id
        test_cmd = ""
        if sub_id:
            for t in store.get("tasks", []):
                if t.get("id") == sub_id:
                    test_cmd = t.get("test_cmd") or ""
                    context.subtask_title = t.get("title", "")
                    break
        context.test_cmd = test_cmd

    # Tasks.SelectNext — deterministic route
    tasks_select = (Node()
        .name("Tasks.SelectNext")
        .tools(["tasks_get_next_decision"])
        .instructions(
            "Call tasks_get_next_decision. It returns 'recommend': red|green|refactor.\n"
            "- If recommend=='red': route to Implement.Red\n"
            "- If recommend=='green': route to Implement.Green\n"
            "- If recommend=='refactor': route to Implement.Refactor\n"
            "- If status=='done': route to Done."
        )
        .input("Pick the next subtask and route based on the recommendation.")
        .budget(6)
    )

    # Red — tests only; exit must be a failing test (pytest rc==1)
    red = (Node()
        .name("Implement.Red")
        .tools(["read_file_content", "apply_file_edits_tests", "run_pytest", "inspect_test_quality", "tasks_update"])
        .instructions(
            "Create a minimal failing test for the current subtask.\n"
            "- Use apply_file_edits_tests with edits=[{path, op:'create'|'modify', content}] to write tests only.\n"
            "- Determine the test path from test_cmd (before '::'); e.g., tests/test_scaffold.py.\n"
            "- Call inspect_test_quality(file_path=<that path>, mode='scaffold' if the test focuses on repo structure; otherwise 'behavior').\n"
            "- If ok==false, fix the test and re-run the quality check. Do NOT use assert False or pytest.fail.\n"
            "- When quality passes, call run_pytest(expr={test_cmd}); it must classify 'fail' (rc==1)."
        )
        .exit(kind="shell", expect="fail", cmd="{test_cmd}")
        .pre(pre_set_current_task_context)
        .input("Create a failing, substantive test (Red). Use only the allowed tools and pass the quality check.")
        .budget(12)
    )


    # Green — src only; tests must NOT be edited
    green = (Node()
        .name("Implement.Green")
        .tools(["read_file_content", "apply_file_edits_src", "run_pytest", "tasks_update"])
        .instructions(
            "Make the failing test pass with the smallest code change.\n"
            "- Use apply_file_edits_src (no tests allowed) to edit src only.\n"
            "- Then run run_pytest(expr={test_cmd}) and run_pytest() for the full suite; both must classify 'pass'."
        )
        .exit(kind="shell", expect="pass", cmd="{test_cmd}")
        .pre(pre_set_current_task_context)
        .input("Make the test pass (Green). Use only the allowed tools.")
        .budget(12)
    )

    # Refactor — src only; tests must remain untouched; suite must stay green
    refactor = (Node()
        .name("Implement.Refactor")
        .tools(["read_file_content", "apply_file_edits_src", "run_pytest", "tasks_update", "list_directory"])
        .instructions(
            "Refactor mechanically without changing behavior. Do not modify tests.\n"
            "- Use apply_file_edits_src to avoid touching tests.\n"
            "- Use list_directory to inspect the tree instead of reading directories as files.\n"
            "- Run run_pytest() afterwards; it must classify 'pass'."
        )
        .exit(kind="shell", expect="pass", cmd="pytest -q")
        .pre(pre_set_current_task_context)
        .input("Refactor safely. Use only the allowed tools.")
        .budget(8)
    )

    # Review/Commit — deterministic finalize
    review_commit = (Node()
        .name("Review.Commit")
        .tools(["tasks_get", "run_pytest", "git_commit", "tasks_mark_done", "tasks_progress"])
        .instructions(
            "Finalize the current subtask:\n"
            "1) run_pytest() — suite must classify 'pass'.\n"
            "2) git_commit(message='<conventional commit>') — auto-initializes repo if needed.\n"
            "3) tasks_mark_done() — mark current subtask DONE. If this completes a parent, it becomes DONE.\n"
            "4) Optionally call tasks_progress() and briefly summarize.\n"
            "5) If any PENDING subtasks remain, route to Tasks.SelectNext; else route to Done."
        )
        .input("Finalize and commit changes for this subtask.")
        .budget(10)
    )

    done = (Node()
        .name("Done")
        .instructions("All tasks complete. Provide a brief wrap-up and stop.")
        .input("Finish.")
        .budget(1)
    )

    # Routes
    qna_iterate.routes({ worktype_decide._id: "Clarity bar reached (problem, goals, primary user, acceptance sketch)." })
    worktype_decide.routes({ prd_draft._id: "Work type is 'coding'." })
    prd_draft.routes({ plan_review._id: "PRD JSON drafted or updated." })
    plan_review.routes({ tasks_parent._id: "PRD sane: each FR has acceptance idea, runner known." })
    tasks_parent.routes({ tasks_subtasks._id: "Parent tasks created." })
    tasks_subtasks.routes({ tasks_select._id: "Subtasks created with test_cmd or plan for Red." })
    tasks_select.routes({
        red._id: "Next subtask needs a failing test (no test_cmd or test currently passes).",
        green._id: "Next subtask has a failing test (rc != 0)."
    })
    red.routes({ green._id: "Exit gate satisfied: failing test observed (rc != 0)." })
    green.routes({ refactor._id: "Exit gate satisfied: targeted test passes and full suite passes." })
    refactor.routes({ review_commit._id: "Refactor done; tests green." })
    review_commit.routes({
        tasks_select._id: "More tasks remain (PENDING exist).",
        done._id: "All tasks DONE."
    })

    # Add nodes
    graph.add_nodes([
        qna_iterate, worktype_decide, prd_draft, plan_review,
        tasks_parent, tasks_subtasks, tasks_select,
        red, green, refactor, review_commit, done
    ])

    # Expose nodes by name for resume logic
    nodes = {
        "QnA.Iterate": qna_iterate,
        "WorkType.Decide": worktype_decide,
        "PRD.Draft": prd_draft,
        "Plan.Review": plan_review,
        "Tasks.ParentPlan": tasks_parent,
        "Tasks.Subtasks": tasks_subtasks,
        "Tasks.SelectNext": tasks_select,
        "Implement.Red": red,
        "Implement.Green": green,
        "Implement.Refactor": refactor,
        "Review.Commit": review_commit,
        "Done": done,
    }
    return graph, nodes

# ----------------------------
# Resume chooser
# ----------------------------
def compute_resume_start(nodes: dict[str, Node]) -> Node:
    """
    Decide where to (re)start based on .agent/prd.json and .agent/tasks.json
    """
    prd = _read_json(PRD_PATH, {})
    tasks = _read_json(TASKS_PATH, {"parents": [], "tasks": [], "current": {"subtask_id": None}})

    # If we have a current subtask, try to jump straight into implement loop
    cur = tasks.get("current", {}).get("subtask_id")
    if cur:
        sub = next((t for t in tasks.get("tasks", []) if t.get("id") == cur), None)
        test_cmd = (sub or {}).get("test_cmd")
        if test_cmd:
            # Run the test to see if we should go Green or Refactor
            res = ToolRegistry.call("execute_shell_command", {"command": test_cmd, "cwd": context.cwd})
            rc = res.get("return_code", 1 if res.get("status") != "success" else 0)
            if rc != 0:
                return nodes["Implement.Green"]  # failing test exists
            else:
                return nodes["Implement.Refactor"]  # already passing → cleanups/commit
        else:
            return nodes["Implement.Red"]  # no test yet

    # No current subtask: see if any tasks remain
    any_pending = any(t.get("status") == "PENDING" for t in tasks.get("tasks", []))
    if any_pending:
        return nodes["Tasks.SelectNext"]

    # Parents exist but no subtasks yet → expand subtasks
    if tasks.get("parents") and not tasks.get("tasks"):
        return nodes["Tasks.Subtasks"]

    # PRD exists with FRs → create parent tasks
    frs = prd.get("functional_requirements", [])
    if isinstance(frs, list) and len(frs) > 0:
        return nodes["Tasks.ParentPlan"]

    # PRD drafted minimally → review
    if prd.get("title") or prd.get("overview"):
        return nodes["Plan.Review"]

    # Default: start fresh
    return nodes["QnA.Iterate"]

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, help="Initial user prompt")
    parser.add_argument("--cwd", type=str, help="Repository root")
    parser.add_argument("--resume", action="store_true", help="Try to pick up where you left off")
    args = parser.parse_args()

    seed_cwd(args.cwd)

    if args.prompt:
        context.user_prompt = args.prompt
    else:
        try:
            context.user_prompt = input("Enter your initial prompt: ").strip()
        except EOFError:
            context.user_prompt = ""
    if not context.user_prompt:
        context.user_prompt = "Untitled task"

    graph, nodes = build_graph()

    # Choose start node (resume-aware)
    start_node = compute_resume_start(nodes) if args.resume else nodes["QnA.Iterate"]

    # Run; open model console on pause; handle stop tickets; resume until complete
    while True:
        context.running = True
        context.paused = False
        context.next_node = start_node
        graph.run(start_node)

        if getattr(context, "paused", False):
            model_console()
            # Recompute a smart resume point after console Q&A
            start_node = compute_resume_start(nodes)
            continue

        if handle_open_stops():
            # Recompute resume point after answering stop questions
            start_node = compute_resume_start(nodes)
            continue

        break  # finished
