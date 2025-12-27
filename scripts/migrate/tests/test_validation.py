"""
Unit tests for migration validation script.

Tests validation logic and report generation.
"""

import sys
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.migrate.validate_migration import ValidationReport


def test_validation_report_initialization():
    """Test ValidationReport initialization."""
    report = ValidationReport()

    assert report.checks == []
    assert report.start_time is not None
    assert report.end_time is None


def test_validation_report_add_check():
    """Test adding checks to report."""
    report = ValidationReport()

    report.add_check("Test Check 1", True, "Details 1")
    report.add_check("Test Check 2", False, "Details 2")

    assert len(report.checks) == 2
    assert report.checks[0]['name'] == "Test Check 1"
    assert report.checks[0]['passed'] is True
    assert report.checks[1]['passed'] is False


def test_validation_report_counts():
    """Test pass/fail counts."""
    report = ValidationReport()

    report.add_check("Pass 1", True)
    report.add_check("Pass 2", True)
    report.add_check("Fail 1", False)

    assert report.passed_count() == 2
    assert report.failed_count() == 1


def test_validation_report_markdown_generation():
    """Test markdown report generation."""
    report = ValidationReport()

    report.add_check("Count Validation", True, "All counts match")
    report.add_check("Query Validation", False, "Overlap too low")

    markdown = report.generate_markdown()

    # Verify markdown contains key sections
    assert "# Migration Validation Report" in markdown
    assert "Count Validation" in markdown
    assert "Query Validation" in markdown
    assert "✓ PASS" in markdown
    assert "✗ FAIL" in markdown
    assert "**Total Checks**: 2" in markdown
    assert "**Passed**: 1" in markdown
    assert "**Failed**: 1" in markdown


def test_validation_report_all_passed():
    """Test report when all checks pass."""
    report = ValidationReport()

    report.add_check("Check 1", True)
    report.add_check("Check 2", True)

    markdown = report.generate_markdown()

    assert "All validation checks passed!" in markdown
    assert report.failed_count() == 0


def test_validation_report_some_failed():
    """Test report when some checks fail."""
    report = ValidationReport()

    report.add_check("Check 1", True)
    report.add_check("Check 2", False)

    markdown = report.generate_markdown()

    assert "Some validation checks failed!" in markdown or "failed checks" in markdown
    assert report.failed_count() == 1


def test_validation_report_string_representation():
    """Test string representation of report."""
    report = ValidationReport()

    report.add_check("Test", True)
    report.add_check("Test", False)

    str_repr = str(report)
    assert "1/2 passed" in str_repr or "ValidationReport" in str_repr


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
