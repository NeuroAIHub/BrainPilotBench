# Qualitative review guide (candidate)

The six dimensions in `rubric.yaml` are for a separate human review of the submitted report and implementation. They do not enter the candidate's objective `score`; no automatic LLM judgment has been validated for this integration.

Review only the public reconstruction, the task instructions, and the submitted artifacts. The evaluator-only reconstructions and expected numerical answers must not be used as prompts or examples for a contestant-facing review. If a reviewer needs private results for an internal audit, keep that review outside the Agent's feedback channel.

For each dimension, use a 1–5 scale: 5 means the stated criterion is supported by inspectable evidence; 3 means it is mostly supported with a material omission; 1 means it is missing or contradicted. Record file/line or reported numerical evidence and a short reason. A style preference alone must not change a scientific score.

- Correctness: inspect whether code implements the declared method on arbitrary input arrays. The objective scorer separately checks its numerical output.
- Evidence: require each main claim to point to its measured value and comparison level.
- Consistency: distinguish the one public reconstruction from unmeasured reconstructions.
- Methodology: inspect treatment of missing pairs, null models, chance levels, community topology, and hub choice.
- Calibration: preserve null, boundary, and noncomputable outcomes rather than forcing a positive conclusion.
- Presentation: make methods, results, units, and scope easy to trace.

A qualitative review is pending expert calibration. Do not report a rubric score as independent scientific acceptance or merge it into the objective metric.
