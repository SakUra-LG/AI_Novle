import argparse
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bert_excitation_train.scripts.v2.theme_constraints import (
    BACKGROUND as DEFAULT_BACKGROUND,
    THEME as DEFAULT_THEME,
    protagonists_arg,
)


def run_step(step_name: str, args: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> None:
    print(f"[v2/generate_v2_pipeline] Running step: {step_name} -> {' '.join(args)}")
    result = subprocess.run(args, capture_output=False, text=True, cwd=cwd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {step_name} (exit {result.returncode})")


def chapter_bounds(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    values: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if "-" in token:
            left, right = token.split("-", 1)
            if left.strip().isdigit() and right.strip().isdigit():
                values.update(range(min(int(left), int(right)), max(int(left), int(right)) + 1))
        elif token.isdigit():
            values.add(int(token))
    return (min(values), max(values)) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified V2 pipeline in scripts/v2: clusters -> outline -> chapters"
    )
    parser.add_argument("--project-config", type=str, default=None)
    parser.add_argument("--generation-config", type=str, default=None)
    parser.add_argument("--chapters", type=str, default=None, help="e.g. 1,2,3")
    parser.add_argument("--total-chapters", type=int, default=100)
    parser.add_argument(
        "--final-arc-len", type=int, default=8,
        help="Number of chapters reserved for the final arc; forwarded to event-cluster generation.",
    )
    parser.add_argument("--output-dir", type=str, default=None, help="Override all V2 outputs (useful for isolated runs).")
    parser.add_argument("--theme", type=str, default=DEFAULT_THEME)
    parser.add_argument("--background", type=str, default=DEFAULT_BACKGROUND)
    parser.add_argument("--protagonists", type=str, default=protagonists_arg())
    parser.add_argument("--extra-constraints", type=str, default="")
    parser.add_argument("--extra-constraints-file", type=str, default=None)
    parser.add_argument("--workdir", type=str, default=None)
    parser.add_argument("--python", type=str, default=sys.executable)
    parser.add_argument("--skip-clusters", action="store_true")
    parser.add_argument("--reuse-seed-plan", action="store_true")
    parser.add_argument("--skip-outline", action="store_true")
    parser.add_argument("--skip-chapters", action="store_true")
    parser.add_argument("--skip-neo4j-build", action="store_true")
    parser.add_argument("--neo4j-reset", action="store_true")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip interactive prompts in v2 cluster generation script.",
    )
    args = parser.parse_args()

    repo_root = Path(args.workdir or Path(__file__).resolve().parents[3])
    scripts_dir = repo_root / "bert_excitation_train" / "scripts" / "v2"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "bert_excitation_train" / "outputs"
    runtime_env = os.environ.copy()
    runtime_env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "V2_THEME": args.theme,
        "V2_THEME_TITLE": args.theme,
        "V2_BACKGROUND": args.background,
        "V2_PROTAGONISTS": args.protagonists,
        "V2_EXTRA_CONSTRAINTS": args.extra_constraints.strip(),
        "V2_OUTPUT_DIR": str(output_dir),
        "V2_CHAPTERS_DIR": str(output_dir / "chapters_v2"),
        "STORY_MEMORY_TRACE_FILE": str(output_dir / "knowledge_graph" / "story_memory_trace.jsonl"),
    })

    project_cfg = args.project_config or str(repo_root / "bert_excitation_train" / "config" / "project_configs.json")
    generation_cfg = args.generation_config or str(repo_root / "bert_excitation_train" / "config" / "generation_config.json")

    if not args.skip_clusters:
        cmd = [
            args.python,
            str(scripts_dir / "generate_event_clusters_v2.py"),
            "--project-config",
            project_cfg,
            "--generation-config",
            generation_cfg,
            "--theme",
            args.theme,
            "--background",
            args.background,
            "--protagonists",
            args.protagonists,
            "--total-chapters",
            str(max(2, args.total_chapters)),
            "--final-arc-len",
            str(max(1, args.final_arc_len)),
        ]
        merged_extra = args.extra_constraints.strip()
        if merged_extra:
            cmd += ["--extra-constraints", merged_extra]
        if args.extra_constraints_file:
            cmd += ["--extra-constraints-file", args.extra_constraints_file]
        if args.non_interactive:
            cmd.append("--non-interactive")
        if args.reuse_seed_plan:
            cmd.append("--reuse-seed-plan")
        run_step("event_clusters_v2", cmd, cwd=str(repo_root), env=runtime_env)

    if not args.skip_outline:
        run_step(
            "outline_from_clusters_v2",
            [
                args.python,
                str(scripts_dir / "generate_outline_from_event_clusters_v2.py"),
                "--total-chapters",
                str(max(2, args.total_chapters)),
            ],
            cwd=str(repo_root), env=runtime_env,
        )

    if not args.skip_chapters:
        if not args.skip_neo4j_build:
            bootstrap_cmd = [
                args.python,
                "-m",
                "bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j",
            ]
            if args.neo4j_reset:
                bootstrap_cmd.append("--reset")
            run_step("neo4j_bootstrap_kg", bootstrap_cmd, cwd=str(repo_root), env=runtime_env)

            run_step(
                "neo4j_build_plot_clusters",
                [
                    args.python,
                    "-m",
                    "bert_excitation_train.scripts.neo4j_kg.build_plot_clusters",
                    "--clusters-config",
                    str(output_dir / "event_clusters_v2.json"),
                ],
                cwd=str(repo_root), env=runtime_env,
            )

        cmd = [
            args.python,
            str(scripts_dir / "generate_chapter_content_v2.py"),
            "--chapters-dir",
            str(output_dir / "chapters"),
        ]
        if args.skip_neo4j_build:
            cmd.append("--skip-neo4j-sync")
        bounds = chapter_bounds(args.chapters)
        if bounds:
            cmd += ["--start", str(bounds[0]), "--end", str(bounds[1])]
        run_step("chapter_content_v2", cmd, cwd=str(repo_root), env=runtime_env)

        if not args.skip_neo4j_build:
            build_cmd = [
                args.python,
                "-m",
                "bert_excitation_train.scripts.neo4j_kg.build_from_chapters",
                "--min-name-freq",
                "5",
            ]
            run_step("neo4j_build_from_chapters", build_cmd, cwd=str(repo_root), env=runtime_env)

    print("[v2/generate_v2_pipeline] Done.")


if __name__ == "__main__":
    main()

