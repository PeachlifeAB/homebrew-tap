Feature: Configured vault authentication recovery
  Scenario: Recover rejected authentication using stored credentials
    Given the user has unlocked the login keychain
    And Sive holds credentials for the configured vault
    When Bitwarden rejects authentication during refresh
    Then Sive logs in once using stored credentials
    And refresh continues without another master-password prompt

  Scenario: Preserve a healthy session
    Given Bitwarden accepts the stored vault password
    When Sive acquires a configured vault session
    Then Sive does not log out or log in

  Scenario: Stop when recovery requires another factor
    Given Bitwarden rejects authentication during refresh
    When recovery login requires an additional factor
    Then Sive stops with actionable guidance
    And Sive does not repeat the login attempt
