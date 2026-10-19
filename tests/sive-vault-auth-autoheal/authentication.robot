*** Settings ***
Library    Process

*** Test Cases ***
Configured Vault Authentication Recovery
    ${result}=    Run Process    uv    run    pytest    packages/sive/tests/test_vault_session.py    -q
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}\n${result.stderr}
