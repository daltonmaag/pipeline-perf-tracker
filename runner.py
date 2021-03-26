from abc import abstractclassmethod
import json
import math
import os
import re
import shlex
import subprocess
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import venv
import yaml


def main():
    NUMBER_OF_TIMES = 3
    try:
        old_results = Results.from_file("results/results.json")
    except OSError:
        old_results = Results()
    new_results = Results()
    scenarios = Scenario.load_all()
    projects = Project.load_all()
    for scenario in scenarios:
        if scenario.disabled:
            continue
        for project in projects:
            if project.can_handle(scenario):
                for variant in scenario.variants:
                    for version in project.versions:
                        result = old_results.get(scenario, variant, project, version)
                        print(
                            f'Running "{scenario.name}" variant "{variant.id}" using "{project.name}" version "{version.id}"',
                            end="",
                        )
                        if result is None or not result.success:
                            print("... ")
                            result = run(
                                scenario, variant, project, version, NUMBER_OF_TIMES
                            )
                        else:
                            print(": already done.")
                        if result is not None:
                            new_results.set(scenario, variant, project, version, result)
    new_results.save("results/results.json")
    with open("index.template.html", "r") as fp:
        template = fp.read()
    with open("results/index.html", "w") as fp:
        fp.write(template.replace("REPLACE_ME_WITH_JSON", json.dumps(new_results.data)))


@dataclass
class Result:
    cmd: str
    success: bool
    output: str
    clock_time_ms: float
    cpu_time_ms: float

    def get_data(self):
        return asdict(self)

    @staticmethod
    def from_data(data):
        return Result(**data)


class ScenarioSources:
    @abstractclassmethod
    def download(self, path):
        pass

    @staticmethod
    def from_data(data):
        if data == "bundled":
            return ScenarioSourcesBundled()
        elif "git" in data:
            return ScenarioSourcesGit(data["git"]["repository"], data["git"]["ref"])
        raise ValueError(f"Unknown scenario source data: {data}")


BUNDLED_SOURCES = Path("bundled_sources/").resolve()


@dataclass
class ScenarioSourcesBundled:
    def download(self, path: Path):
        os.makedirs(path, exist_ok=True)
        # Make symlinks in path to the bundled_sources folders
        for child in BUNDLED_SOURCES.iterdir():
            target = (path / child.name)
            if not target.is_symlink():
                target.symlink_to(child, child.is_dir())


@dataclass
class ScenarioSourcesGit:
    repository: str
    ref: str

    def download(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            git("-C", path, "remote", "update")
        else:
            git("clone", self.repository, path)
        git("-c", "advice.detachedHead=false", "-C", path, "checkout", self.ref)


@dataclass
class ScenarioVariant:
    id: str
    sources: ScenarioSourcesGit
    variables: Dict

    def get_variables(self, path):
        return {
            variable: [str(path / subpath) for subpath in paths]
            for variable, paths in self.variables.items()
        }

    @staticmethod
    def from_data(data):
        return ScenarioVariant(
            data["id"], ScenarioSources.from_data(data["sources"]), data["variables"]
        )


@dataclass
class Scenario:
    id: str
    name: str
    description: str
    variants: List[ScenarioVariant]
    disabled: bool

    @staticmethod
    def from_data(id, data):
        return Scenario(
            id,
            data["name"],
            data["description"],
            [ScenarioVariant.from_data(v) for v in data["variants"]],
            "disabled" in data
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
        # TODO: virtualenv is faster and better
        venv.create(project_path, with_pip=True)
        cmd = "\n".join(["source bin/activate", *self.setup_script])
        print(f"    Running setup_script:")
        print(textwrap.indent(cmd, " " * 8))
        subprocess.check_call(cmd, shell=True, executable="/bin/bash", cwd=project_path)

    @staticmethod
    def from_data(data):
        return ProjectVersion(**data)


TIME_OUTPUT_RE = re.compile(r"real (\d+\.\d+)\nuser (\d+\.\d+)\nsys (\d+\.\d+)")


@dataclass
class Project:
    id: str
    name: str
    url: str
    description: str
    scenarios: List[Dict]
    versions: List[ProjectVersion]

    def can_handle(self, scenario):
        return any(s["id"] == scenario.id for s in self.scenarios)

    def run(
        self, project_path: Path, scenario: Scenario, variables: Dict, times: int
    ) -> Result:
        before_script = []
        timed_script = []
        after_script = []
        for s in self.scenarios:
            if s["id"] == scenario.id:
                before_script = s.get("before_script", [])
                timed_script = s["timed_script"]
                after_script = s.get("after_script", [])
        cmd = "\n".join(
            [
                "{",
                "set -e",
                "source bin/activate",
                *(
                    f"export {variable}={list_of_quoted_paths(paths)}"
                    for variable, paths in variables.items()
                ),
                *before_script,
                # Use GNU time to output the results to a file,
                # -p for portable output for easy parsing
                # TODO: if we're just measuring python stuff anyway, and we want
                # more types of data (cpu, memory, gpu...) we could use scalene instead.
                "/usr/bin/time -p -o time.txt bash -c {}".format(
                    shlex.quote(
                        "; ".join(
                            [
                                "set -e",
                                f"for i in $(seq {times})",
                                "do echo '######## Run number '$i",
                                *timed_script,
                                "done",
                            ]
                        )
                    )
                ),
                *after_script,
                "} 2>&1 | tee output.txt",
            ]
        )
        print(f"    Running script:")
        print(textwrap.indent(cmd, " " * 8))
        code = subprocess.call(
            cmd,
            shell=True,
            executable="bash",
            cwd=project_path,
        )
        output = "<no output>"
        try:
            with (project_path / "output.txt").open("r") as fp:
                output = fp.read()
        except:
            pass
        real = user = sys = float("nan")
        try:
            with (project_path / "time.txt").open("r") as fp:
                match = TIME_OUTPUT_RE.match(fp.read())
                if match is not None:
                    real = float(match.group(1))
                    user = float(match.group(2))
                    sys = float(match.group(3))
        except:
            pass
        return Result(
            cmd,
            code == 0 and not math.isnan(real),
            output,
            real * 1000 / times,
            (user + sys) * 1000 / times,
        )

    @staticmethod
    def from_data(id, data):
        return Project(
            id,
            data["name"],
            data["url"],
            data["description"],
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
        lambda match: list_of_quoted_paths(variables[match.group(1)])
        if match.group(1) in variables
        else match.group(0),
        line,
    )


def list_of_quoted_paths(paths):
    return " ".join([shlex.quote(path) for path in paths])


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
        if project.id not in self.data["values"][scenario.id][variant.id]:
            self.data["values"][scenario.id][variant.id][project.id] = {}
        self.data["values"][scenario.id][variant.id][project.id][
            version.id
        ] = stats.get_data()
        # Also record scenario and project data to display nicely on web page
        if "scenarios" not in self.data:
            self.data["scenarios"] = {}
        self.data["scenarios"][scenario.id] = {
            "name": scenario.name,
            "description": scenario.description,
        }
        if "projects" not in self.data:
            self.data["projects"] = {}
        self.data["projects"][project.id] = {
            "name": project.name,
            "url": project.url,
            "description": project.description,
        }

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


DOWNLOADS = Path("downloads/").resolve()
VENVS = Path("venvs/").resolve()


def run(
    scenario: Scenario,
    variant: ScenarioVariant,
    project: Project,
    version: ProjectVersion,
    times: int,
) -> Optional[Result]:
    try:
        sources_path = (
            DOWNLOADS / safe_dir_name(scenario.id) / safe_dir_name(variant.id)
        )
        variant.sources.download(sources_path)
        variables = variant.get_variables(sources_path)
        project_path = VENVS / safe_dir_name(project.id) / safe_dir_name(version.id)
        version.setup(project_path)
        result = project.run(project_path, scenario, variables, times)
        return result
    except Exception as e:
        print(f"Could not run: {e}")
        return None


def git(*args):
    """Execute the given git command and return the output."""
    return subprocess.check_output(["git", *args])


if __name__ == "__main__":
    main()
