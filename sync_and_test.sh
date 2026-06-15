#!/bin/bash
# sync_and_test.sh — Synchronisiert Produktiv-Code und startet Tests
# Verwendung: ./sync_and_test.sh [beliebige pytest-Argumente]
#
# Beispiele:
#   ./sync_and_test.sh                                          # Alle Tests
#   ./sync_and_test.sh --cov=custom_components/busch_radio_inet # Mit Coverage
#   ./sync_and_test.sh tests/test_config_flow.py               # Einzelne Datei

set -e

INTEGRATION="busch_radio_inet"

echo "=== Synchronisiere custom_components/$INTEGRATION → tests/custom_components/$INTEGRATION ==="
rsync -a --delete "custom_components/$INTEGRATION/" "tests/custom_components/$INTEGRATION/"
echo "=== Synchronisation abgeschlossen ==="

echo ""
echo "=== Starte Tests ==="
pytest "$@"
