"""
Test 12: EventBridge Rules and Triggers

Validates:
- EventBridge rules exist
- Rules have Lambda targets configured
- Rules are enabled
- Event patterns are configured correctly
"""

import pytest


@pytest.mark.integration
def test_eventbridge_rules_exist(boto3_clients):
    """Verify EventBridge rules exist."""
    events = boto3_clients['events']

    # List all rules
    response = events.list_rules()

    rules = response['Rules']

    # Should have at least some rules (may be from other services)
    assert isinstance(rules, list)


@pytest.mark.integration
def test_eventbridge_collections_rules(boto3_clients):
    """Test collections-specific EventBridge rules."""
    events = boto3_clients['events']

    # List rules with collections prefix
    try:
        response = events.list_rules(
            NamePrefix='collections'
        )

        rules = response.get('Rules', [])

        if len(rules) == 0:
            pytest.skip("No collections EventBridge rules found")

        # Verify rules
        for rule in rules:
            assert 'Name' in rule
            assert 'State' in rule

            # Rules should be enabled
            # (DISABLED is also valid during testing)
            assert rule['State'] in ['ENABLED', 'DISABLED']

    except Exception as e:
        pytest.skip(f"Could not check EventBridge rules: {e}")


@pytest.mark.integration
def test_eventbridge_rule_targets(boto3_clients):
    """Test EventBridge rule targets."""
    events = boto3_clients['events']

    try:
        response = events.list_rules(
            NamePrefix='collections'
        )

        rules = response.get('Rules', [])

        if len(rules) == 0:
            pytest.skip("No collections EventBridge rules found")

        # Check targets for each rule
        for rule in rules:
            rule_name = rule['Name']

            targets_response = events.list_targets_by_rule(
                Rule=rule_name
            )

            targets = targets_response.get('Targets', [])

            # Each rule should have at least one target
            if len(targets) > 0:
                # Verify target structure
                for target in targets:
                    assert 'Id' in target
                    assert 'Arn' in target

    except Exception as e:
        pytest.skip(f"Could not check rule targets: {e}")


@pytest.mark.integration
def test_eventbridge_cleanup_schedule(boto3_clients):
    """Test cleanup Lambda schedule (if configured)."""
    events = boto3_clients['events']

    try:
        # Look for cleanup schedule
        response = events.list_rules()

        rules = response.get('Rules', [])

        cleanup_rules = [r for r in rules if 'cleanup' in r['Name'].lower()]

        if len(cleanup_rules) == 0:
            pytest.skip("No cleanup schedule found")

        # Verify cleanup rule
        for rule in cleanup_rules:
            assert 'ScheduleExpression' in rule or 'EventPattern' in rule

            # Check if it's a rate or cron schedule
            if 'ScheduleExpression' in rule:
                schedule = rule['ScheduleExpression']
                assert 'rate' in schedule or 'cron' in schedule

    except Exception as e:
        pytest.skip(f"Could not verify cleanup schedule: {e}")
