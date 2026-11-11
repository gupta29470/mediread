# mediread-sft-v0

Pilot instruction-tuning set for the on-device explanation model. Every example is
generated deterministically by `mediread.training`; **no teacher model is used** and
`provenance.teacher` is null for every row.

| | |
|---|---|
| examples | 65 |
| schema | `mediread.sft-example/1` |
| splits | {'train': 49, 'validation': 8, 'test': 8} |
| unique tests | 6 |
| unique evidence rows | 26 |
| invalid rejected | 0 |
| duplicates removed | 0 |
| near-duplicate pairs | 33 |
| family leakage | 0 |

## Category distribution

| category | count | achieved share | target share |
|---|---|---|---|
| adversarial | 3 | 5% | 5% |
| extraction_uncertainty | 2 | 3% | 5% |
| follow_up | 1 | 2% | 5% |
| high_low | 12 | 18% | 15% |
| missing_information | 2 | 3% | 10% |
| qualitative | 6 | 9% | 5% |
| result_explanation | 18 | 28% | 20% |
| safety_refusal | 4 | 6% | 10% |
| test_explanation | 12 | 18% | 35% |
| unsupported_test | 5 | 8% | 15% |

## Rules enforced by validation

- the answer may only state numbers and ranges supplied in the prompt facts;
- no diagnosis, treatment, medication change, urgency or invented citation;
- the last chat message is the assistant answer and equals `output`;
- categories, splits and provenance fields are from fixed vocabularies;
- no PII-looking strings.

## Splits

Split by *family* (the knowledge test id, or the template family when there is no
knowledge). A family is entirely in one split, so paraphrases of the same source
cannot leak between train and test. The frozen 21-case benchmark in
`src/mediread/llm_eval/` is not read by this pipeline and is not part of the set.

## Known limits

- Only tests with `reviewed`/`approved` knowledge produce knowledge-grounded
  examples; the current package has 6 reviewed tests, so the knowledge-grounded
  categories are small. The generator scales with review, not with synthetic volume.
- Numeric values in `result_explanation` and `high_low` examples are synthetic
  placeholders stated in the prompt; they are not reference intervals from the
  knowledge package.

## Human review

High-risk categories (safety refusal, adversarial, unsupported) are listed in
`report.json` under `human_review_sample`; review is pending.
