# Characterization tests, per framework

A characterization test records what the code does **now**. It is not a statement that the behavior
is correct — it is a tripwire. Read only the `§<framework>` section for the runner `ad-test detect`
reported.

Every section has the same four parts: **Shape**, **Stubbing I/O**, **Probe**, **Pitfalls**.

The probe is the part people skip. Never write an expected value you predicted; run the node once,
copy what it actually returned, and paste that. A predicted value that happens to be wrong turns a
characterization test into a bug report against working code.

---

## pytest

### Shape

```python
import pytest
from mymodule import target_fn

# inputs taken from real call sites, not invented
CASES = [
    (("alpha", 3), "ALPHA-3"),
    (("beta", 0), "BETA-0"),
]


@pytest.mark.parametrize("args,expected", CASES)
def test_target_fn_characterization(args, expected):
    """Pins current behavior. A failure here means behavior changed."""
    assert target_fn(*args) == expected
```

### Stubbing I/O

Stub every callee `ad-graph node` tagged `io`. `monkeypatch` scopes to the test and unwinds itself:

```python
def test_reads_config(monkeypatch, tmp_path):
    monkeypatch.setattr("mymodule.read_config", lambda path: {"mode": "fast"})
    assert target_fn("x") == "x-fast"
```

Use `tmp_path` for anything that must be a real file. Never point a test at a path outside it.

### Probe

```python
def test_probe():          # delete this once the value is copied into CASES
    print(repr(target_fn("alpha", 3)))
    assert False           # forces pytest to show the captured stdout
```

Run `ad-test run --select tests/test_target.py::test_probe`, read the `repr`, paste it as `expected`,
delete the probe.

### Pitfalls

- **Time**: `datetime.now()` in the output makes the test pass once. Freeze it —
  `monkeypatch.setattr("mymodule.datetime", FixedDatetime)`.
- **Random**: seed it, or stub the generator. `random.seed(0)` is not enough if the node uses
  `secrets` or `uuid4`.
- **Dict order**: stable within a run, not across Python versions for anything built from a `set`.
  Assert `sorted(...)`, or compare dicts rather than their `repr`.
- **Floats**: `assert x == 0.30000000000000004` is a trap. Use `pytest.approx`.
- **Windows paths**: a golden string containing `\\` passes on the laptop and fails on CI. Normalize
  with `.replace("\\", "/")` on both sides, the way `agentdata` does everywhere.
- **Encoding**: a fixture written by PowerShell 5.1 carries a UTF-8 BOM or is UTF-16. Read it through
  `agentdata/textio.py`, never bare `open()`.

---

## unittest

### Shape

```python
import unittest
from mymodule import target_fn


class TargetFnCharacterization(unittest.TestCase):
    """Pins current behavior. A failure here means behavior changed."""

    def test_alpha(self):
        self.assertEqual(target_fn("alpha", 3), "ALPHA-3")

    def test_beta(self):
        self.assertEqual(target_fn("beta", 0), "BETA-0")
```

Use `subTest` when the cases share one body:

```python
    def test_cases(self):
        for args, expected in [(("alpha", 3), "ALPHA-3")]:
            with self.subTest(args=args):
                self.assertEqual(target_fn(*args), expected)
```

### Stubbing I/O

```python
from unittest.mock import patch

    @patch("mymodule.read_config", return_value={"mode": "fast"})
    def test_reads_config(self, _read):
        self.assertEqual(target_fn("x"), "x-fast")
```

Patch the name **where it is used**, not where it is defined. Use `tempfile.TemporaryDirectory()`
for real files.

### Probe

```python
    def test_probe(self):      # delete once copied
        raise AssertionError(repr(target_fn("alpha", 3)))
```

The `repr` appears in the failure message. Copy it into the assertion and delete the probe.

### Pitfalls

- **Time**: patch `mymodule.datetime`, not `datetime.datetime` — the latter is immutable.
- **Random**: `@patch("mymodule.random.choice", side_effect=[...])` is more reliable than a seed.
- **Dict order**: `assertEqual` on dicts already ignores order; on their `repr` it does not.
- **Floats**: `assertAlmostEqual`, not `assertEqual`.
- **Windows paths**: `os.path.join` produces `\` — normalize before comparing to a literal.
- **Encoding**: pass `encoding="utf-8"` explicitly; the platform default differs on Windows.

---

## Jest

### Shape

```javascript
const { targetFn } = require("../src/mymodule");

describe("targetFn characterization", () => {
  // inputs taken from real call sites
  test.each([
    [["alpha", 3], "ALPHA-3"],
    [["beta", 0], "BETA-0"],
  ])("targetFn(%p)", (args, expected) => {
    expect(targetFn(...args)).toBe(expected);
  });
});
```

### Stubbing I/O

```javascript
jest.mock("../src/config", () => ({ readConfig: () => ({ mode: "fast" }) }));
```

For filesystem access use `jest.spyOn(fs, "readFileSync").mockReturnValue("...")` and restore it in
`afterEach`. Never let a test read a path outside the repo's temp directory.

### Probe

```javascript
test("probe", () => {
  console.log(JSON.stringify(targetFn("alpha", 3)));
  expect(true).toBe(false);   // delete once the value is copied
});
```

### Pitfalls

- **Time**: `jest.useFakeTimers().setSystemTime(new Date("2020-01-01"))`, and restore afterwards.
- **Random**: `jest.spyOn(Math, "random").mockReturnValue(0.5)`.
- **Object key order**: `toEqual` ignores it; `toBe` on a `JSON.stringify` result does not.
- **Floats**: `toBeCloseTo`, not `toBe`.
- **Windows paths**: `path.join` yields `\` on Windows. Compare with `path.posix` or normalize.
- **Line endings**: a golden string of file content differs by `\r\n` on Windows checkouts. Strip
  `\r` on both sides.

---

## xUnit (.NET)

### Shape

```csharp
public class TargetFnCharacterization
{
    // inputs taken from real call sites
    [Theory]
    [InlineData("alpha", 3, "ALPHA-3")]
    [InlineData("beta", 0, "BETA-0")]
    public void PinsCurrentBehavior(string name, int n, string expected)
        => Assert.Equal(expected, Target.Fn(name, n));
}
```

### Stubbing I/O

Inject the dependency and pass a fake, or use Moq:

```csharp
var config = new Mock<IConfigReader>();
config.Setup(c => c.Read(It.IsAny<string>())).Returns(new Config { Mode = "fast" });
Assert.Equal("x-fast", new Target(config.Object).Fn("x"));
```

A static file read that cannot be injected is a finding for `## Open questions`, not something to
work around in the test.

### Probe

```csharp
[Fact]
public void Probe()                       // delete once copied
    => Assert.Equal("", Target.Fn("alpha", 3));
```

The assertion message prints the actual value. Copy it into `InlineData` and delete the probe.

### Pitfalls

- **Time**: `DateTime.Now` is untestable — inject an `IClock`, or pin `DateTime.UtcNow` behind a
  seam. Note it in `## Open questions` if neither exists.
- **Random**: pass a seeded `Random`; the parameterless constructor differs across runtimes.
- **Dictionary order**: `Dictionary<K,V>` enumeration order is not contractual. Compare sorted.
- **Floats**: `Assert.Equal(expected, actual, precision: 4)`.
- **Windows paths**: golden strings from `Path.Combine` are `\`-separated; normalize before
  comparing, and never assert on an absolute path.
- **Culture**: `ToString()` on a number or date is culture-sensitive. Pin
  `CultureInfo.InvariantCulture` in the assertion.
