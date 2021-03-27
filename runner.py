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
    scenarios = [s for s in Scenario.load_all() if not s.disabled]
    projects = [p for p in Project.load_all() if not p.disabled]
    for project in projects:
        for version in project.versions:
            print("\n# Environment %s/%s\n" % (project.id, version.id))
            project_path = VENVS / safe_dir_name(project.id) / safe_dir_name(version.id)
            try:
                version.setup(project_path)
            except Exception as e:
                print(
                    "::warning::Could not set up %s/%s - %s"
                    % (project.id, version.id, e)
                )
                continue

            for scenario in scenarios:
                if not project.can_handle(scenario):
                    continue
                for variant in scenario.variants:
                    sources_path = (
                        DOWNLOADS
                        / safe_dir_name(scenario.id)
                        / safe_dir_name(variant.id)
                    )
                    result = old_results.get(scenario, variant, project, version)
                    print(
                        f'::group::Running "{scenario.name}" variant "{variant.id}" using "{project.name}" version "{version.id}"'
                    )
                    if result is None or not result.success:
                        print("... ")
                        variant.sources.download(sources_path)
                        variables = variant.get_variables(sources_path)
                        result = project.run(
                            project_path, scenario, variables, NUMBER_OF_TIMES
                        )
                    else:
                        print(": already done.")
                    if result is not None:
                        new_results.set(scenario, variant, project, version, result)
                    print("::endgroup::")
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
    clock_times_ms: List[float]
    cpu_times_ms: List[float]

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
            target = path / child.name
            if not target.is_symlink():
                target.symlink_to(child, child.is_dir())


@dataclass
class ScenarioSourcesGit:
    repository: str
    ref: str

    def download(self, path):
        print("::group::Downloading %s from %s/%s" % (path, self.repository, self.ref))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            git("-C", path, "remote", "update")
        else:
            git("clone", "--depth", "1", self.repository, path)
        git("-c", "advice.detachedHead=false", "-C", path, "checkout", self.ref)
        print(" Download complete\n")
        print("::endgroup")


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
            "disabled" in data,
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
        print(f"::group::Running setup_script for {self.description}")
        print(textwrap.indent(cmd, " " * 8))
        subprocess.check_call(cmd, shell=True, executable="/bin/bash", cwd=project_path)
        print("::endgroup::")

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
    disabled: bool

    def can_handle(self, scenario):
        return any(s["id"] == scenario.id for s in self.scenarios)

    def run(
        self, project_path: Path, scenario: Scenario, variables: Dict, times: int
    ) -> Result:
        before_script = []
        timed_command = []
        after_script = []
        for s in self.scenarios:
            if s["id"] == scenario.id:
                before_script = s.get("before_script", [])
                timed_command = s["timed_command"].split()
                after_script = s.get("after_script", [])
        runner_script = Path.cwd() / "run-timed.py"

        substituted_args = []
        for ix, arg in enumerate(timed_command):
            if arg.startswith("$") and arg[1:] in variables:
                substituted_args.extend(
                    [shlex.quote(path) for path in variables[arg[1:]]]
                )
            else:
                substituted_args.append(arg)

        cmd = "\n".join(
            [
                "{",
                "set -e",
                "source bin/activate",
                *before_script,
                # Use GNU time to output the results to a file,
                # -p for portable output for easy parsing
                # TODO: if we're just measuring python stuff anyway, and we want
                # more types of data (cpu, memory, gpu...) we could use scalene instead.
                "python {} --times {} {}".format(
                    runner_script, times, " ".join(substituted_args)
                ),
                *after_script,
                "}",
            ]
        )
        print(f"    Running script:")
        print(textwrap.indent(cmd, " " * 8))
        out_file = (project_path / "output.txt").open("w")
        code = subprocess.call(
            cmd,
            shell=True,
            executable="bash",
            cwd=project_path,
            stdout=out_file,
            stderr=out_file,
        )
        if code != 0:
            print("::warning::Script returned %i" % code)
        output = "<no output>"
        try:
            with (project_path / "output.txt").open("r") as fp:
                output = fp.read()
        except:
            pass
        real = cpu = [float("nan")]
        try:
            timing = json.load(open(project_path / "times.json"))
            real = [t.get("clock") * 1000 / times for t in timing]
            cpu = [t.get("cpu") * 100 / times for t in timing]
        except Exception as e:
            print("::warning::Couldn't load timings: %s" % e)
        return Result(cmd, code == 0, output, real, cpu)

    @staticmethod
    def from_data(id, data):
        return Project(
            id,
            data["name"],
            data["url"],
            data["description"],
            data["scenarios"],
            [ProjectVersion.from_data(v) for v in data["versions"]],
            "disabled" in data,
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


def git(*args):
    """Execute the given git command and return the output."""
    return subprocess.check_output(["git", *args])


if __name__ == "__main__":
    main()
