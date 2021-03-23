import json
import os
import re
import shlex
import subprocess
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

import venv
import yaml


def main():
    try:
        old_results = Results.from_file("results.json")
    except OSError:
        old_results = Results()
    new_results = Results()
    scenarios = Scenario.load_all()
    projects = Project.load_all()
    for scenario in scenarios:
        for project in projects:
            if project.can_handle(scenario):
                for variant in scenario.variants:
                    for version in project.versions:
                        result = old_results.get(scenario, variant, project, version)
                        print(
                            f'Running "{scenario.name}" variant "{variant.id}" using "{project.name}" version "{version.id}"',
                            end="",
                        )
                        if result is None:
                            print("... ")
                            result = run(scenario, variant, project, version)
                        else:
                            print(": already done.")
                        new_results.set(scenario, variant, project, version, result)
    new_results.save("results.json")


@dataclass
class Result:
    user_time_ms: int
    cpu_time_ms: int

    def get_data(self):
        return asdict(self)

    @staticmethod
    def from_data(data):
        return Result(**data)


@dataclass
class ScenarioSourcesGit:
    repository: str
    ref: str

    def download(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            git("clone", self.repository, path)
        git("-c", "advice.detachedHead=false", "-C", path, "checkout", self.ref)

    @staticmethod
    def from_data(data):
        return ScenarioSourcesGit(data["git"]["repository"], data["git"]["ref"])


@dataclass
class ScenarioVariant:
    id: str
    sources: ScenarioSourcesGit
    variables: Dict

    def get_variables(self, path):
        return {
            variable: [path / subpath for subpath in paths]
            for variable, paths in self.variables.items()
        }

    @staticmethod
    def from_data(data):
        return ScenarioVariant(
            data["id"], ScenarioSourcesGit.from_data(data["sources"]), data["variables"]
        )


@dataclass
class Scenario:
    id: str
    name: str
    variants: List[ScenarioVariant]

    @staticmethod
    def from_data(id, data):
        return Scenario(
            id, data["name"], [ScenarioVariant.from_data(v) for v in data["variants"]]
        )

    @staticmethod
    def load_all():
        result = []
        for path in Path("scenarios/").glob("*.yml"):
            try:
                with path.open("r") as fp:
                    data = yaml.safe_load(fp)
                    result.append(Scenario.from_data(path.stem, data))
            except Exception as e:
                print(f"Could not load {path}: {e}")
        return result


@dataclass
class ProjectVersion:
    id: str
    description: str
    setup_script: List[str]

    def setup(self, project_path: Path):
        venv.create(project_path)
        cmd = "\n".join(["source bin/activate", *self.setup_script])
        subprocess.call(cmd, shell=True, executable="/bin/bash", cwd=project_path)

    @staticmethod
    def from_data(data):
        return ProjectVersion(**data)


@dataclass
class Project:
    id: str
    name: str
    scenarios: List[Dict]
    versions: List[ProjectVersion]

    def can_handle(self, scenario):
        return any(s["id"] == scenario.id for s in self.scenarios)

    def run(self, project_path: Path, scenario: Scenario, variables: Dict) -> Result:
        script = []
        for s in self.scenarios:
            if s["id"] == scenario.id:
                script = s["script"]
        cmd = "\n".join(
            [
                "source bin/activate",
                *(replace_variables(line, variables) for line in script),
            ]
        )
        print(f"    Running cmd:")
        print(textwrap.indent("\n".join(cmd), " " * 8))
        subprocess.call(
            cmd, shell=True, executable="bash", cwd=project_path, env=variables
        )
        return Result(1000, 2000)

    @staticmethod
    def from_data(id, data):
        return Project(
            id,
            data["name"],
            data["scenarios"],
            [ProjectVersion.from_data(v) for v in data["versions"]],
        )

    @staticmethod
    def load_all():
        result = []
        for path in Path("projects/").glob("*.yml"):
            try:
                with path.open("r") as fp:
                    data = yaml.safe_load(fp)
                    result.append(Project.from_data(path.stem, data))
            except Exception as e:
                print(f"Could not load {path}: {e}")
        return result


VARIABLE_RE = re.compile(r"\$([A-Z_][A-Z_0-9]*)")


def replace_variables(line, variables):
    return VARIABLE_RE.sub(
        lambda match: " ".join(
            [shlex.quote(path) for path in variables[match.group(1)]]
        ),
        line,
    )


@dataclass
class Results:
    data: Dict = field(default_factory=dict)

    def get(
        self,
        scenario: Scenario,
        variant: ScenarioVariant,
        project: Project,
        version: ProjectVersion,
    ) -> Optional[Result]:
        data = (
            self.data.get("values", {})
            .get(scenario.id, {})
            .get(variant.id, {})
            .get(project.id, {})
            .get(version.id, None)
        )
        if data is not None:
            return Result.from_data(data)
        return None

    def set(
        self,
        scenario: Scenario,
        variant: ScenarioVariant,
        project: Project,
        version: ProjectVersion,
        stats: Result,
    ):
        if "values" not in self.data:
            self.data["values"] = {}
        if scenario.id not in self.data["values"]:
            self.data["values"][scenario.id] = {}
        if variant.id not in self.data["values"][scenario.id]:
            self.data["values"][scenario.id][variant.id] = {}
        if project.id not in self.data["values"][scenario.id]:
            self.data["values"][scenario.id][variant.id][project.id] = {}
        self.data["values"][scenario.id][variant.id][project.id][
            version.id
        ] = stats.get_data()

    def save(self, path):
        with open(path, "w") as fp:
            json.dump(self.data, fp)

    @staticmethod
    def from_file(path):
        with open(path, "r") as fp:
            data = json.load(fp)
            return Results(data)


UNSAFE_DIR_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def safe_dir_name(string):
    return UNSAFE_DIR_NAME_RE.sub("_", string)


DOWNLOADS = Path("downloads/")
VENVS = Path("venvs/")


def run(
    scenario: Scenario,
    variant: ScenarioVariant,
    project: Project,
    version: ProjectVersion,
) -> Optional[Result]:
    sources_path = DOWNLOADS / safe_dir_name(scenario.id) / safe_dir_name(variant.id)
    variant.sources.download(sources_path)
    variables = variant.get_variables(sources_path)
    project_path = VENVS / safe_dir_name(project.id) / safe_dir_name(version.id)
    version.setup(project_path)
    result = project.run(project_path, scenario, variables)
    return result


def git(*args):
    """Execute the given git command and return the output."""
    return subprocess.check_output(["git", *args])


if __name__ == "__main__":
    main()
