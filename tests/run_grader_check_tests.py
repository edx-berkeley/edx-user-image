#!/usr/bin/env python3
"""
Execute student and solution notebooks inside a Docker container and check grader.check results.

For each notebook pair in tests/test_files/:
  - Student notebook: at least one grader.check cell must FAIL (solutions are stripped)
  - Solution notebook: all grader.check cells must PASS

Usage:
  python tests/run_grader_check_tests.py
  python tests/run_grader_check_tests.py --image edx-user-image:pr
  python tests/run_grader_check_tests.py --image gcr.io/data8x-scratch/edx-user-image:latest
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEST_FILES_DIR = Path("tests/test_files")
DEFAULT_IMAGE = "gcr.io/data8x-scratch/edx-user-image:latest"


def run_notebook_in_docker(image, nb_path, work_dir, raise_on_error=True):
    """
    Execute a notebook in Docker. Returns the parsed output notebook JSON.
    work_dir must already contain the notebook and all companion files.
    """
    cmd = [
        "docker", "run", "--rm",
        # Match the host UID/GID so the container can write into /work AND
        # the host can clean up after — using -u root left .pyc files owned
        # by root that tempfile.TemporaryDirectory cleanup couldn't unlink.
        # HOME=/tmp avoids jupyter complaining about an unwritable home.
        "-u", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/tmp",
        "-v", f"{work_dir.resolve()}:/work",
        "-w", "/work",
        image,
        "jupyter", "nbconvert",
        "--to", "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout=300",
        "--output", nb_path.name,
        nb_path.name,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if raise_on_error and result.returncode != 0:
        # nbconvert writes CellExecutionError tracebacks to stderr, but harmless
        # python warnings (e.g. subprocess line-buffering RuntimeWarning) also
        # land there. Concatenate stdout too so the real error isn't masked.
        combined = (
            f"exit={result.returncode}\n"
            f"--- stdout ---\n{result.stdout[-2000:]}\n"
            f"--- stderr ---\n{result.stderr[-2000:]}"
        )
        raise RuntimeError(combined)
    output_nb = work_dir / nb_path.name
    if not output_nb.exists():
        raise RuntimeError(f"Output notebook not found after execution: {output_nb}")
    return json.loads(output_nb.read_text())


def scan_check_outputs(nb):
    """
    Scan cells that call grader.check() and classify their outputs as pass or fail.
    Returns (pass_count, fail_count).
    """
    passes, failures = 0, 0
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", []))
        if "grader.check(" not in src:
            continue
        output_text = ""
        for out in cell.get("outputs", []):
            for key in ("text", "text/plain", "text/html"):
                val = out.get("data", {}).get(key) or out.get(key)
                if val:
                    output_text += "".join(val) if isinstance(val, list) else val
        if output_text and ("All test cases passed" in output_text or "passed!" in output_text.lower()):
            passes += 1
        else:
            failures += 1
    return passes, failures


def run_pair(image, course, section, assignment):
    student_src = TEST_FILES_DIR / course / section / assignment / "student"
    solution_src = TEST_FILES_DIR / course / section / assignment / "solution"
    nb_name = f"{assignment}.ipynb"

    if not (student_src / nb_name).exists() or not (solution_src / nb_name).exists():
        print(f"  [skip] {course}/{section}/{assignment}: notebook pair not present")
        return True, []

    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        for role, src_dir, expect_pass in [
            ("student",  student_src,  False),
            ("solution", solution_src, True),
        ]:
            # Copy all files from the role directory into a clean work dir
            role_work = work / role
            shutil.copytree(src_dir, role_work)
            nb_in_work = role_work / nb_name

            print(f"  Executing {role} notebook ({course}/{section}/{assignment})...")
            try:
                nb = run_notebook_in_docker(image, nb_in_work, role_work, raise_on_error=expect_pass)
            except RuntimeError as e:
                if expect_pass:
                    errors.append(f"{course}/{section}/{assignment} {role}: execution error\n{e}")
                    print(f"    [FAIL] execution error\n{e}")
                else:
                    # Student notebook raising exceptions is not unexpected (bad answers can error)
                    print(f"    [warn] student notebook raised exception (may be OK)")
                continue

            passes, failures = scan_check_outputs(nb)
            if expect_pass:
                if failures > 0:
                    errors.append(f"{course}/{section}/{assignment} {role}: {failures} check(s) failed")
                    print(f"    [FAIL] {failures} grader.check(s) failed, {passes} passed")
                elif passes == 0:
                    errors.append(f"{course}/{section}/{assignment} {role}: no grader.check output found")
                    print(f"    [FAIL] no grader.check output found")
                else:
                    print(f"    [PASS] all {passes} grader.check(s) passed")
            else:
                if failures == 0:
                    errors.append(
                        f"{course}/{section}/{assignment} {role}: all {passes} check(s) passed — solutions may not be stripped"
                    )
                    print(f"    [FAIL] all {passes} check(s) passed (expected failures)")
                else:
                    print(f"    [PASS] {failures} check(s) failed as expected")

    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()

    pairs = []
    if TEST_FILES_DIR.exists():
        for course_dir in sorted(TEST_FILES_DIR.iterdir()):
            if not course_dir.is_dir():
                continue
            for section_dir in sorted(course_dir.iterdir()):
                if not section_dir.is_dir():
                    continue
                for assignment_dir in sorted(section_dir.iterdir()):
                    if assignment_dir.is_dir():
                        pairs.append((course_dir.name, section_dir.name, assignment_dir.name))

    if not pairs:
        print("No notebook pairs found in tests/test_files/ — nothing to test")
        sys.exit(0)

    all_errors = []
    for course, section, assignment in pairs:
        _, errors = run_pair(args.image, course, section, assignment)
        all_errors.extend(errors)

    if all_errors:
        print(f"\n{len(all_errors)} failure(s):")
        for e in all_errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\nAll {len(pairs)} notebook pair(s) passed grader.check")


if __name__ == "__main__":
    main()
