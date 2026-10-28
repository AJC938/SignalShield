# SignalShield Engineering Report Templates

All statements must distinguish **completed**, **tested**, **partially implemented**, and **planned**. A command belongs in “executed” only if it was actually run. Include failures and deviations, not only successful results. User-facing explanatory sections should be written in clear Arabic with standard English engineering terms; code and formal API names remain English.

## Engineering task report

```markdown
# Task <ID> — <Title>

## Status
- Implementation: <completed / partial / planned>
- Verification: <tested / not tested / blocked; explain>

## 1. Objective
<Task goal and dependency gate.>

## 2. Design decision and rationale
<Choice, alternatives considered, mathematical/API implications.>

## 3. Files created or modified
- `<path>` — <responsibility/change>

## 4. Implemented conventions and algorithms
<Equations, units, normalization, RNG and edge behavior.>

## 5. Commands actually executed
```text
<exact command>
<exit status and concise real output>
```

## 6. Tests actually executed
| Command/test | Outcome | Evidence / failure details |
|---|---|---|

## 7. Experiments and numerical results
<Configuration, seed, N, errors, estimate, interval, theory if valid. Say “not performed” if none.>

## 8. Artifacts produced
<Plots/result files with paths and what they show.>

## 9. Deviations
<None, or exact deviation and documented rationale.>

## 10. Known failures, limitations, unresolved questions
<Do not omit unresolved items.>

## 11. Reproduction
<Environment and exact commands/config path.>

## 12. شرح بالعربية
<ما الذي نُفذ ولماذا، وما الذي تثبته نتائج التحقق وحدودها.>

## 13. Engineering lesson
<One concise lesson.>

## 14. Next dependency-ready task
<Task ID, prerequisites satisfied, next concrete action.>
```

## Final system validation report

```markdown
# SignalShield Final System Validation Report

## 1. System and environment
<Commit/revision, OS, Python and library versions, installation method.>

## 2. Scope validated
<Implemented capabilities; list unimplemented conditional/excluded items.>

## 3. Mathematical conventions
<Reference/waveform energy and noise convention, filters, delays, gain assumptions.>

## 4. Validation summary
| Acceptance ID | Status | Command/config | Actual evidence | Limitation |
|---|---|---|---|---|

## 5. Experiment results
<For each experiment include question, config, seed, sample count, errors, BER/interval, theory where valid, candidate-vs-baseline result, runtime if measured. No invented or rounded-away zero-error bounds.>

## 6. Generated artifacts
<CSV/JSON/plots and paths. Distinguish theory curves from simulation data.>

## 7. Failures, deviations and known limitations
<Complete list; include any flaky or environment-specific behavior.>

## 8. Reproduction instructions
<Clean setup and exact commands to rerun tests and experiments.>

## 9. Conclusion
<What evidence supports, what it does not establish, and whether acceptance gates passed.>

## 10. الخلاصة بالعربية
<شرح واضح لما يفعله النظام، وما أثبتته القياسات فعلًا، وأهم القيود.>

## 11. Portfolio summary and interview prompts
<Concise technically accurate summary and 5–10 questions the author can defend.>
```
