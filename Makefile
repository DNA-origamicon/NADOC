.PHONY: smoketest update-smokeref pre-commit-install

# Run the full end-to-end pipeline smoke test (<45 min on production GPU).
# Exits 0 on success, 1 on any failure or reference mismatch.
smoketest:
	python tests/smoke/run.py

# Re-generate the checked-in reference_params.json after a known-good pipeline change.
# Commit the updated reference alongside the code change.
update-smokeref:
	python tests/smoke/run.py --update-reference

# Install git pre-commit hook that blocks commits if the smoke test fails.
# The hook runs the smoke test before every commit — slow but safe.
# Use `git commit --no-verify` to bypass in emergencies.
pre-commit-install:
	@echo '#!/bin/sh' > .git/hooks/pre-commit
	@echo 'echo "[pre-commit] Running NADOC pipeline smoke test..."' >> .git/hooks/pre-commit
	@echo 'make smoketest' >> .git/hooks/pre-commit
	@echo 'if [ $$? -ne 0 ]; then' >> .git/hooks/pre-commit
	@echo '    echo "[pre-commit] Smoke test FAILED — commit blocked."' >> .git/hooks/pre-commit
	@echo '    exit 1' >> .git/hooks/pre-commit
	@echo 'fi' >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed. Run 'make smoketest' manually, or it runs on every commit."
