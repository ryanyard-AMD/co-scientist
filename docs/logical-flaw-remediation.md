# Logical Flaw Remediation

This document tracks the implementation steps for the logic review findings and
the tests that guard each fix.

## Step 1: Hypothesis LLM Fallback

Problem:

- Hypothesis generation promised deterministic synthesis when no Anthropic key
  is available, but a locally configured invalid key forced tests and normal
  generation through the LLM path.
- The test harness loaded `.env`, so local credentials could change unit-test
  behavior.

Fix:

- Tests now force `CS_HYPOTHESIS_USE_LLM=false` before importing the application.
- Hypothesis generation catches Anthropic API failures and logs a governance
  entry before falling back to deterministic synthesis.

Coverage:

- `tests/test_hypothesis_api.py`
- `tests/test_hypothesis_service.py`
