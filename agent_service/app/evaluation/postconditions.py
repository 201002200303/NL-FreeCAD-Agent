from app.evaluation.validators import run_geometry_validators


def evaluate_postconditions(postconditions: list[str], **kwargs) -> list[dict]:
    """V0.8 postconditions are represented by validator names in the first release."""
    validator_names = [item for item in postconditions if item.startswith("verify_")]
    return run_geometry_validators(validator_names, **kwargs)

