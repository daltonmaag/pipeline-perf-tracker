import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, TypedDict
from pathlib import Path

import yaml


@dataclass
class Scenario:
    id: str
    name: str

    @staticmethod
    def from_data(id, data):
        return Scenario(id, data['name'])

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

    @staticmethod
    def from_data(data):
        return ProjectVersion(data['id'])


@dataclass
class Project:
    id: str
    name: str
    scenarios: List[Dict]
    versions: List[ProjectVersion]

    def can_handle(self, scenario):
        return any(s["id"] == scenario.id for s in self.scenarios)

    @staticmethod
    def from_data(id, data):
        return Project(id, data['name'], data['scenarios'], [ProjectVersion.from_data(v) for v in data['versions']])

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
class Results:
    data: Dict = field(default_factory=dict)

    def get(
        self, scenario: Scenario, project: Project, version: ProjectVersion
    ) -> Optional[Result]:
        data = (
            self.data.get("values", {})
            .get(scenario.id, {})
            .get(project.id, {})
            .get(version.id, None)
        )
        if data is not None:
            return Result.from_data(data)
        return None

    def set(
        self,
        scenario: Scenario,
        project: Project,
        version: ProjectVersion,
        stats: Result,
    ):
        if "values" not in self.data:
            self.data["values"] = {}
        if scenario.id not in self.data["values"]:
            self.data["values"][scenario.id] = {}
        if project.id not in self.data["values"][scenario.id]:
            self.data["values"][scenario.id][project.id] = {}
        self.data["values"][scenario.id][project.id][version.id] = stats.get_data()

    def save(self, path):
        with open(path, "w") as fp:
            json.dump(self.data, fp)

    @staticmethod
    def from_file(path):
        with open(path, "r") as fp:
            data = json.load(fp)
            return Results(data)


def _run(
    scenario: Scenario, project: Project, version: ProjectVersion
) -> Optional[Result]:
    print(f"Running {scenario.name} using {project.name} version {version.id}... ")
    return Result(500, 2000)


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
                for version in project.versions:
                    result = old_results.get(scenario, project, version)
                    if result is None:
                        result = _run(scenario, project, version)
                    new_results.set(scenario, project, version, result)
    new_results.save("results.json")


if __name__ == "__main__":
    main()
