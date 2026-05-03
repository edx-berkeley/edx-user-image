#!/usr/bin/env python3
"""
Execute student and solution notebooks inside a Docker container and check grader.check results.

For each notebook pair in tests/test_files/:
  - Student notebook: at least one grader.check cell must FAIL (solutions are stripped)
  - Solution notebook: all grader.check cells must PASS

Usage:
  python tests/run_grader_check_tests.py
  python tests/run_grader_check_tests.py --image edx-user-image:pr
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEST_FILES_DIR = Path("tests/test_files")
DEFAULT_IMAGE = "gcr.io/data8x-scratch/edx-user-image:latest"


def split_image_name(image):
    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    if last_colon > last_slash:
        return image[:last_colon], image[last_colon + 1 :]
    return image, None


def list_local_images():
    result = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:])
    return [line.strip() for line in result.stdout.splitlines() if line.strip() and not line.endswith(":<none>")]


def resolve_image(image):
    local_images = list_local_images()
    if image in local_images:
        return image

    repository, _ = split_image_name(image)
    candidates = [local_image for local_image in local_images if split_image_name(local_image)[0] == repository]
    if candidates:
        resolved = candidates[0]
        print(f"Using local image {resolved} because requested image {image} was not found")
        return resolved

    return image


def run_notebook_in_docker(image, nb_path, work_dir, raise_on_error=True):
    """
    Execute a notebook in Docker. Returns the parsed output notebook JSON.
    work_dir must already contain the notebook and all companion files.
    """
    output_name = f"executed-{nb_path.stem}"
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_dir.resolve()}:/work",
        "-w", "/work",
        image,
        "jupyter", "nbconvert",
        "--to", "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout=300",
        f"--ExecutePreprocessor.raise_on_ioerror={'True' if raise_on_error else 'False'}",
        "--output", output_name,
        nb_path.name,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output_nb = work_dir / f"{output_name}.ipynb"
    if result.returncode != 0 and (raise_on_error or not output_nb.exists()):
        raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:])
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


def run_pair(image, course, assignment):
    student_src = TEST_FILES_DIR / course / assignment / "student"
    solution_src = TEST_FILES_DIR / course / assignment / "solution"
    nb_name = f"{assignment}.ipynb"

    if not (student_src / nb_name).exists() or not (solution_src / nb_name).exists():
        print(f"  [skip] {course}/{assignment}: notebook pair not present")
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

            print(f"  Executing {role} notebook ({course}/{assignment})...")
            try:
                nb = run_notebook_in_docker(image, nb_in_work, role_work, raise_on_error=expect_pass)
            except RuntimeError as e:
                if expect_pass:
                    errors.append(f"{course}/{assignment} {role}: execution error — {str(e)[:300]}")
                    print(f"    [FAIL] execution error")
                else:
                    # Student notebook raising exceptions is not unexpected (bad answers can error)
                    print(f"    [warn] student notebook raised exception (may be OK): {str(e)[:200]}")
                continue

            passes, failures = scan_check_outputs(nb)
            if expect_pass:
                if failures > 0:
                    errors.append(f"{course}/{assignment} {role}: {failures} check(s) failed")
                    print(f"    [FAIL] {failures} grader.check(s) failed, {passes} passed")
                elif passes == 0:
                    errors.append(f"{course}/{assignment} {role}: no grader.check output found")
                    print(f"    [FAIL] no grader.check output found")
                else:
                    print(f"    [PASS] all {passes} grader.check(s) passed")
            else:
                if failures == 0:
                    errors.append(
                        f"{course}/{assignment} {role}: all {passes} check(s) passed — solutions may not be stripped"
                    )
                    print(f"    [FAIL] all {passes} check(s) passed (expected failures)")
                else:
                    print(f"    [PASS] {failures} check(s) failed as expected")

    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()
    image = resolve_image(args.image)

    pairs = []
    if TEST_FILES_DIR.exists():
        for course_dir in sorted(TEST_FILES_DIR.iterdir()):
            if not course_dir.is_dir():
                continue
            for assignment_dir in sorted(course_dir.iterdir()):
                if assignment_dir.is_dir():
                    pairs.append((course_dir.name, assignment_dir.name))

    if not pairs:
        print("No notebook pairs found in tests/test_files/ — nothing to test")
        sys.exit(0)

    all_errors = []
    for course, assignment in pairs:
        _, errors = run_pair(image, course, assignment)
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
