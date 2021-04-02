# UFO Performance Tracker

A tracker for performance improvements across the UFO libraries inspired by
arewefastyet.com

Tested on Ubuntu on WSL2. Should work on Linux and macOS, not windows (because
it uses /usr/bin/time to measure time... to be improved!)

To setup a fresh Ubuntu:

```bash
sudo apt install python3-pip
pip3 install poetry
```

To run this script:

```bash
poetry install
poetry run python runner.py
```

The results of the runs are stored both in `results/results.json` and embedded
into `results/index.html`.

## How to contribute

### Add a "project" = a font-related library that can execute some scenarios

Add a file called `projects/<your_project_name>.yml`. See the commented example below of the `fontmake` compiler:

```yaml
# Identification of the project, to be shown in the results
name: fontmake TTF output
url: https://github.com/googlefonts/fontmake
description: fontmake in its default configuration, only TTF output

# Instructions to install the project's code and its dependencies.
# The project can come in different version to compare them against each other.
# Each version is identified by a unique id and a free-text description.
# 
# The `setup_script` is a list of lines of bash script.
# They will be evaluated inside a fresh Python environment,
# different for each version of the project.
versions:
  - id: git-main-ufo2ft-avoid-reloading
    description: Nikolaus version that avoid copying fonts during compilation
    setup_script:
      - python -m pip install --upgrade pip
      - python -m pip install fontmake==2.4.0
      - python -m pip install "fonttools[ufo,lxml,unicode] @ git+git://github.com/fonttools/fonttools@0e5fe2d1d7"
      - python -m pip install git+git://github.com/googlefonts/ufo2ft@avoid-font-reloading
  - id: v2.4.0
    description: official release
    setup_script:
      - python -m pip install --upgrade pip
      - python -m pip install fontmake==2.4.0

# List scenarios that this project can execute.
#   - The `id` of the scenario matches the file name of its `.yml` file.
#   - Each line of the `before_script` and `after_script` (both optional) is
#     a line of bash script. These are not counted in the runtime of the project.
#   - The `timed_command` is a single python command that will be given to the
#     `run-timed.py` script. It needs to be a Python program because
#     `run-timed.py` will profile it using Python tooling.
#   - All scripts and the timed command can refer to variables from the matching
#     scenario, to access the files to compile. See the scenario file for the
#     available variables.
scenarios:
  - id: narrow_build_vf_from_designspace
    before_script:
      - pip list
    timed_command: fontmake --verbose WARNING -m $DESIGNSPACE -o variable
  - id: narrow_build_vf_from_glyphs
    before_script:
      - pip list
    timed_command: fontmake --verbose WARNING -g $GLYPHS_FILE -o variable
```

### Add a "scenario" = sources to compile, transform etc. using the various projects

Add a file called `scenarios/<your_scenario_name>.yml`. Each scenario can come in several variants.

```yaml
# Identification for the test result page.
name: Narrow build (VF) from Glyphs.app
description: |
  Build a variable font from a Glyphs file.
  Use-cases:
  - Build final variable fonts on CI machines
  - Build test variable fonts on designer's machines
  - ...

# Variants of the scenario. Each variant may demonstrate files of growing sizes
# or different features to support, etc.
#
# Each variant can either:
#   - download files from a public Git repository, such as the "Nunito" variant below.
#     The `repository` is the argument to `git clone`, and the `ref` is the argument
#     to `git checkout`, e.g. a commit id, tag, branch.
#   - use files that are in the `bundled_sources` folder of this repository, such as
#     "Sofia Sans".
#
# Then each variant can define variable that are each a list of file paths, relative
# to the root of the Git repository that was cloned, or the `bundled_sources` folder.
# That's how projects can know which file to process in each scenario.
variants:
  - id: Nunito (1100 glyphs, 6 masters)
    sources:
      git:
        repository: https://github.com/googlefonts/nunito
        ref: ed889dda6d742a0495c1963898e1b3567ab61a15
    variables:
      GLYPHS_FILE:
        - sources/Nunito.glyphs
  - id: Sofia Sans (960 glyphs, 7 masters)
    sources: bundled
    variables:
      GLYPHS_FILE:
        - SofiaSans/SofiaSans-VF-New.glyphs
```
