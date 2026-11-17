#!/usr/bin/env bash
# A fingerprint of the engine's source, used to tell whether the packaged engine is out of date.
engine_signature() { # project root
  ( cd "$1/engine" && find culler run_engine.py engine.spec pyproject.toml -type f \
      ! -name "*.pyc" ! -path "*/assets/models/*" ! -path "*/__pycache__/*" | LC_ALL=C sort | tr '\n' '\0' | xargs -0 shasum | shasum | cut -d' ' -f1 )
}
