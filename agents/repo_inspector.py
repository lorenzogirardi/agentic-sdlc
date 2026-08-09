from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger

logger = get_logger(__name__)

BUILD_INDICATORS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "javascript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
    "Dockerfile": "docker",
    "docker-compose.yaml": "docker-compose",
    "docker-compose.yml": "docker-compose",
    "terraform": "terraform",
    ".terraform": "terraform",
}

TEST_INDICATORS = {
    ".py": "pytest",
    "test_": "pytest",
    "_test.py": "pytest",
    ".test.js": "jest",
    ".spec.js": "jest",
    ".test.ts": "jest",
    "_test.go": "go test",
    ".spec.ts": "jest",
}

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".rb": "Ruby",
    ".tf": "Terraform",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".dockerfile": "Dockerfile",
}

FRAMEWORKS = {
    ("fastapi",): "FastAPI",
    ("flask",): "Flask",
    ("django",): "Django",
    ("actix",): "Actix",
    ("express",): "Express",
    ("gin",): "Gin",
    ("react",): "React",
    ("next",): "Next.js",
}


class RepoInspectorOutput(BaseModel):
    languages: list[str] = Field(default_factory=list)
    build_system: str = ""
    test_framework: str = ""
    frameworks: list[str] = Field(default_factory=list)
    has_dockerfile: bool = False
    has_docker_compose: bool = False
    has_terraform: bool = False
    has_observability_config: bool = False
    total_files: int = 0
    directory_structure: list[str] = Field(default_factory=list)
    dockerfile_paths: list[str] = Field(default_factory=list)
    terraform_paths: list[str] = Field(default_factory=list)
    test_paths: list[str] = Field(default_factory=list)
    detected_tools: list[str] = Field(default_factory=list)


class RepoInspectorAgent(Agent):
    name = "repo_inspector"

    async def analyze(self, ctx: AgentContext) -> dict:
        repo_path = Path(ctx.execution.task.repository_path)
        if not repo_path.exists():
            logger.warning("repo_not_found", path=str(repo_path))
            return RepoInspectorOutput().model_dump()

        result = self._scan_repo(repo_path)
        return result.model_dump()

    async def execute(self, ctx: AgentContext) -> dict:
        output = await self.analyze(ctx)
        return {
            "agent_name": self.name,
            "success": True,
            "summary": f"Detected {len(output.get('languages', []))} language(s), "
            f"build: {output.get('build_system', 'none')}, "
            f"test: {output.get('test_framework', 'none')}",
            "output": output,
        }

    async def verify(self, ctx: AgentContext, result: dict) -> dict:
        output = result.get("output", {})
        issues: list[str] = []
        if not output.get("languages"):
            issues.append("No languages detected")
        if not output.get("build_system"):
            issues.append("No build system detected")
        return {"verified": len(issues) == 0, "issues": issues}

    def _scan_repo(self, root: Path) -> RepoInspectorOutput:
        top_items = sorted(
            [p.name for p in root.iterdir() if not p.name.startswith(".")],
        )[:20]

        all_files: list[Path] = []
        extensions: dict[str, int] = {}
        dockerfile_paths: list[str] = []
        terraform_paths: list[str] = []
        test_paths: list[str] = []
        detected_tools: set[str] = set()

        for path in root.rglob("*"):
            if path.is_file() and not any(part.startswith(".") for part in path.parts):
                rel = str(path.relative_to(root))
                all_files.append(path)

                name = path.name.lower()
                ext = path.suffix.lower()

                if ext:
                    extensions[ext] = extensions.get(ext, 0) + 1

                if name in BUILD_INDICATORS:
                    detected_tools.add(BUILD_INDICATORS[name])

                if "test" in name or "spec" in name:
                    test_paths.append(rel)
                    for indicator, tool in TEST_INDICATORS.items():
                        if indicator in name and tool not in detected_tools:
                            pass

                if ext in TEST_INDICATORS:
                    test_paths.append(rel)

                if name == "Dockerfile" or name.endswith(".dockerfile"):
                    dockerfile_paths.append(rel)

                if ext == ".tf" or name.endswith(".tf.json"):
                    terraform_paths.append(rel)

        detected_tools.discard("docker")
        detected_tools.discard("docker-compose")
        detected_tools.discard("terraform")

        if any(p.name in ("Dockerfile",) or p.suffix.lower() == ".dockerfile" for p in all_files):
            detected_tools.add("docker")

        if any(p.name in ("docker-compose.yaml", "docker-compose.yml") for p in all_files):
            detected_tools.add("docker-compose")

        has_terraform = any(p.suffix.lower() == ".tf" for p in all_files)
        if has_terraform:
            detected_tools.add("terraform")

        langs = sorted(
            [lang for ext, lang in LANGUAGE_EXTENSIONS.items() if ext in extensions],
            key=lambda x: extensions.get(f".{x.lower()}", 0),
            reverse=True,
        )

        primary_ext = max(extensions.keys(), key=lambda k: extensions[k]) if extensions else ""
        lang_for_tests = LANGUAGE_EXTENSIONS.get(primary_ext, "")
        test_framework = ""
        for ext, tool in TEST_INDICATORS.items():
            if ext in extensions or any(ext in tp for tp in test_paths):
                test_framework = tool
                break
        if not test_framework and lang_for_tests:
            lang_map = {
                "Python": "pytest",
                "JavaScript": "jest",
                "TypeScript": "jest",
                "Go": "go test",
                "Rust": "cargo test",
            }
            test_framework = lang_map.get(lang_for_tests, "unknown")

        has_docker = any(p.name == "Dockerfile" for p in all_files)
        has_compose = any(
            p.name in ("docker-compose.yaml", "docker-compose.yml") for p in all_files
        )

        frameworks: set[str] = set()
        for framework_keys, framework_name in FRAMEWORKS.items():
            for p in all_files:
                content_hint = ""
                try:
                    if p.suffix in (".py", ".js", ".ts", ".toml", ".json"):
                        content_hint = p.read_text(errors="ignore")[:2000].lower()
                except Exception:
                    pass
                if any(fk in content_hint for fk in framework_keys):
                    frameworks.add(framework_name)

        return RepoInspectorOutput(
            languages=langs[:5] if langs else ["unknown"],
            build_system=BUILD_INDICATORS.get(
                next(
                    (p.name.lower() for p in all_files if p.name.lower() in BUILD_INDICATORS),
                    "",
                ),
                "unknown",
            ),
            test_framework=test_framework or "unknown",
            frameworks=sorted(frameworks),
            has_dockerfile=has_docker,
            has_docker_compose=has_compose,
            has_terraform=has_terraform,
            has_observability_config=any(
                "otel" in p.name.lower() or "prometheus" in p.name.lower() for p in all_files
            ),
            total_files=len(all_files),
            directory_structure=top_items,
            dockerfile_paths=dockerfile_paths[:10],
            terraform_paths=terraform_paths[:10],
            test_paths=test_paths[:10],
            detected_tools=sorted(detected_tools),
        )
