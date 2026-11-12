# Targeted issue triage

This skill investigates a specific issue in any repository in more detail than
the general collection workflow. It checks the report and related context,
attempts safe reproduction, and proposes a solution and regression tests.

Example request:

```text
Use issue-triage to investigate https://github.com/<owner>/<repo>/issues/<number>.
```

The result is a seven-section `issue-<number>-triage.md` report in the directory
where triage was requested, including evidence, a disposition, next action, and a
suggested issue comment. It does not implement fixes or post comments.

Use [SKILL.md](SKILL.md) for this targeted workflow. The general
[`github-issue-triage` workflow](../../../SKILL.md) collects and reviews issues by
repository and label, then opens the viewer. Choose one workflow; use both only
when explicitly requested. Neither workflow automatically triggers the other.
