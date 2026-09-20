"""Apply the unchanged physical-equilibrium fit policy to an isolated campaign."""

from pathlib import Path
import argparse
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import OLD, source, write
from backend.parameterization.photoproduct_response_fit import (
    materialize_quantitative_response_fit_specification,
    evaluate_reviewed_response_fit,
    select_quantitative_response_fit_candidate,
    build_charmm_bonded_transform_candidate,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    args = p.parse_args()
    r = args.stage.resolve()
    policy = r / "fit_policy.json"
    if policy.exists():
        raise FileExistsError(policy)
    shutil.copy2(
        OLD / "physical-equilibrium-fit-v1/photoproduct_response_fit_policy_v4.json",
        policy,
    )
    shutil.copy2(__file__, r / "fit_snapshot.py")
    c = r / "response_campaign/response_campaign_manifest.json"
    s = r / "quantitative_fit_specification.json"
    materialize_quantitative_response_fit_specification(
        campaign_path=c, policy_path=policy, output_path=s
    )
    evaluate_reviewed_response_fit(
        campaign_path=c, specification_path=s, output_dir=r / "evaluation"
    )
    try:
        selected = select_quantitative_response_fit_candidate(
            evaluation_path=r / "evaluation/response_fit_evaluation.json",
            policy_path=policy,
            output_path=r / "selected_response_fit.json",
        )
        build_charmm_bonded_transform_candidate(
            selected_candidate_path=r / "selected_response_fit.json",
            output_path=r / "charmm_bonded_transform.json",
        )
        print(
            json.dumps(
                {
                    "ridge_lambda": selected["ridge_lambda"],
                    "selection_checks": selected["selection_checks"],
                }
            )
        )
    except ValueError as error:
        write(
            r / "selection_failure.json",
            {
                "status": "blocked_candidate_selection",
                "error": str(error),
                "simulation_ready": False,
                "gate_effect": "none",
                "policy": source(policy),
            },
        )
        raise


if __name__ == "__main__":
    main()
