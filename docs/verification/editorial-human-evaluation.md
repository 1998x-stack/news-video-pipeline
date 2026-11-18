# Editorial selection: blind human evaluation

Do not claim Precision@5, NDCG@5 or validated rubric weights without complete independent human annotations.

1. Produce an editorial run, preserving news_items.json, source.txt, editorial_ranking.json and editorial_selection.json.
2. Create **two separate blind label sheets** before showing any model rankings:

    python scripts/editorial_evaluate.py template --run-dir outputs/ACTUAL-RUN --out private/a.json
    python scripts/editorial_evaluate.py template --run-dir outputs/ACTUAL-RUN --out private/b.json

3. Two independent evaluators fill every candidate: relevance 0..3, should_select true/false, must_include true/false, reason. Assign unique pseudonymous annotator_id. Do not overwrite an existing label file; these may be private/untracked.
4. Evaluate after both finish:

    python scripts/editorial_evaluate.py evaluate --run-dir outputs/ACTUAL-RUN --labels private/a.json private/b.json --out private/quality.json

Metrics: Precision@k uses the final selected set divided by k; NDCG@k measures preliminary ranking relevance from human grades 0..3; must_include_recall measures coverage of mandatory human labels. Cohen kappa, binary agreement, selection Jaccard, and disagreement IDs are reported for two raters.

Undefined values are null, never silently treated as zero. The tool refuses stale input hashes, unlabelled candidates, duplicate IDs and the same annotator twice. Evaluation is per episode, not a claim of population-level validation. Collect >=10 distinct episodes and review disagreement before adjusting scoring weights.

Human selection ratings do not verify the truth of sources, copyright, or publication eligibility. They never set public_release_approved.
