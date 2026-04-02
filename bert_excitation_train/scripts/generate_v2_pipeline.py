import argparse
import os
import sys
import subprocess
from pathlib import Path


def run_step(step_name: str, args: list[str], cwd: str | None = None) -> None:
    print(f"[generate_v2_pipeline] Running step: {step_name} -> {' '.join(args)}")
    result = subprocess.run(args, capture_output=False, text=True, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {step_name} (exit {result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified V2 generation pipeline: event clusters -> outline -> chapters"
    )
    parser.add_argument("--project-config", type=str, default=None, help="Optional path to project_configs.json")
    parser.add_argument("--generation-config", type=str, default=None, help="Optional path to generation_config.json")
    parser.add_argument("--chapters", type=str, default=None, help="Comma-separated chapter numbers to generate (e.g., 1,2,3). If omitted, use default in scripts.")
    parser.add_argument("--workdir", type=str, default=None, help="Working directory (defaults to repo root)")
    parser.add_argument("--python", type=str, default=sys.executable, help="Python interpreter to use")
    parser.add_argument("--skip-clusters", action="store_true", help="Skip event clusters step")
    parser.add_argument("--skip-outline", action="store_true", help="Skip outline step")
    parser.add_argument("--skip-chapters", action="store_true", help="Skip chapter generation step")
    parser.add_argument(
        "--skip-neo4j-build",
        action="store_true",
        help="Skip building Neo4j KG from generated chapters (writes to outputs/chapters).",
    )
    parser.add_argument(
        "--neo4j-reset",
        action="store_true",
        help="Danger: wipe all Neo4j nodes/relationships before rebuilding KG (via bootstrap_neo4j --reset).",
    )
    args = parser.parse_args()

    # Resolve repo root
    repo_root = Path(args.workdir or Path(__file__).resolve().parents[2])
    scripts_dir = repo_root / "bert_excitation_train" / "scripts"

    # Optional configs
    project_cfg = args.project_config or str(repo_root / "bert_excitation_train" / "config" / "project_configs.json")
    generation_cfg = args.generation_config or str(repo_root / "bert_excitation_train" / "config" / "generation_config.json")

    # 1) Event clusters (v2)
    if not args.skip_clusters:
        run_step(
            "event_clusters_v2",
            [
                args.python,
                str(scripts_dir / "generate_event_clusters_v2.py"),
                "--project-config",
                project_cfg,
                "--generation-config",
                generation_cfg,
            ],
            cwd=str(repo_root),
        )

    # 2) Outline from clusters (v2)
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

    # 3) Chapter content (v2)
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

        # 4) Neo4j KG build (from generated chapter texts)
        # build_from_chapters 会扫描 outputs/chapters/ 下的 chapter_*.txt 并写入图数据库。
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

    print("[generate_v2_pipeline] Done.")


if __name__ == "__main__":
    main()
