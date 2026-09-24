---
name: A red check (flake)
about: A CI check went red, or red then green on re-run. Open this before any re-run; "flake" is not a root cause.
title: "test: <node id> red on <job>"
labels: flake
---

<!-- docs/testing-this-repo.md, "When CI is red": record, reproduce, fix the cause. Never skip, xfail, quarantine
     or deselect the test, add a fixed wait, raise a cap without a reproduction, or re-run until green. -->

## Job URL
<!-- the failing run's job link -->

## Node id
<!-- tests/test_x.py::test_y[param] -->

## Commit
<!-- the SHA the job ran on -->

## Runner OS and Python
<!-- e.g. windows-latest, Python 3.14.0 -->

## Failure output
<!-- the full output, verbatim, including what _explain_the_page printed -->
```
```

## Reproduction
<!-- how it was reproduced (-n 8 on 4 cores, concurrent copies of the one test, a deterministic trick),
     the command and its output. No fix before this is filled in. -->

## Cause
<!-- a missing condition, a stub race, a leaked global, a product defect. A product defect gets a regression file,
     tests/regressions/test_<yyyymmdd>_<any|shell>_<short>.py, quoting what the runner printed. -->

## Merged over red?
<!-- only at the operator's word for that PR: the PR, and the merge message naming the check and linking this issue.
     Otherwise: no. -->
