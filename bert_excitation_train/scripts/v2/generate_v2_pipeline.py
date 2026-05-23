import argparse
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bert_excitation_train.scripts.v2.theme_constraints import (
    BACKGROUND as DEFAULT_BACKGROUND,
    THEME as DEFAULT_THEME,
    constraints_text,
    protagonists_arg,
)


def run_step(step_name: str, args: list[str], cwd: str | None = None) -> None:
    print(f"[v2/generate_v2_pipeline] Running step: {step_name} -> {' '.join(args)}")
    result = subprocess.run(args, capture_output=False, text=True, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {step_name} (exit {result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified V2 pipeline in scripts/v2: clusters -> outline -> chapters"
    )
    parser.add_argument("--project-config", type=str, default=None)
    parser.add_argument("--generation-config", type=str, default=None)
    parser.add_argument("--chapters", type=str, default=None, help="e.g. 1,2,3")
    parser.add_argument("--theme", type=str, default=DEFAULT_THEME)
    parser.add_argument("--background", type=str, default=DEFAULT_BACKGROUND)
    parser.add_argument("--protagonists", type=str, default=protagonists_arg())
    parser.add_argument("--extra-constraints", type=str, default="")
    parser.add_argument("--extra-constraints-file", type=str, default=None)
    parser.add_argument("--workdir", type=str, default=None)
    parser.add_argument("--python", type=str, default=sys.executable)
    parser.add_argument("--skip-clusters", action="store_true")
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
        ]
        merged_extra = "\n".join(x for x in [constraints_text(), args.extra_constraints.strip()] if x)
        if merged_extra:
            cmd += ["--extra-constraints", merged_extra]
        if args.extra_constraints_file:
            cmd += ["--extra-constraints-file", args.extra_constraints_file]
        if args.non_interactive:
            cmd.append("--non-interactive")
        run_step("event_clusters_v2", cmd, cwd=str(repo_root))

    if not args.skip_outline:
        run_step(
            "outline_from_clusters_v2",
            [
                args.python,
                str(scripts_dir / "generate_outline_from_event_clusters_v2.py"),
                "--project-config",
                project_cfg,
                "--generation-config",
                generation_cfg,
            ],
            cwd=str(repo_root),
        )

    if not args.skip_chapters:
        cmd = [
            args.python,
            str(scripts_dir / "generate_chapter_content_v2.py"),
            "--project-config",
            project_cfg,
            "--generation-config",
            generation_cfg,
        ]
        if args.chapters:
            cmd += ["--chapters", args.chapters]
        run_step("chapter_content_v2", cmd, cwd=str(repo_root))

        if not args.skip_neo4j_build:
            bootstrap_cmd = [
                args.python,
                "-m",
                "bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j",
            ]
            if args.neo4j_reset:
                bootstrap_cmd.append("--reset")
            run_step("neo4j_bootstrap_kg", bootstrap_cmd, cwd=str(repo_root))

            build_cmd = [
                args.python,
                "-m",
                "bert_excitation_train.scripts.neo4j_kg.build_from_chapters",
                "--min-name-freq",
                "5",
            ]
            run_step("neo4j_build_from_chapters", build_cmd, cwd=str(repo_root))

    print("[v2/generate_v2_pipeline] Done.")


if __name__ == "__main__":
    main()

